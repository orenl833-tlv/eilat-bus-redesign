"""Timing the lines against each other: Monte Carlo search over departure times, for the plan AND for today's
network (winter weekday), under real run times and real delays.

Why both: retiming today's lines needs no new routes, so the fair question is how much of the plan's gain is
retiming (possible tomorrow) and how much is the redesign. Both networks get the same search, the same
trips, the same run times and the same delays.

What is searched:
- the plan: each line pattern's departures in a period are a*60 + phase*h (h its headway); one phase per
  pattern (start: 0 for one direction, 0.5 for the other, as exported);
- today: each line direction keeps its printed timetable (with its irregular gaps), shifted as a whole by
  (phase - 0.5) x its typical headway (start: phase 0.5 = the printed timetable).
School lines 80-82 keep today's times in both. Search: N_RANDOM random phase vectors, then coordinate
refinement (each pattern's phase on a grid of GRID values) for SWEEPS sweeps; repeated vectors are memoized.

Score = mean door-to-door minutes (arrival - leaving home) over areas x key places x leaving times, weighted
by the area's residents, planned on the timetable as buses really run:
- each trip runs every street segment in the time measured by GPS at that hour (eilat/speeds.py);
- every trip is delayed as a real trip of its line and hour was (SIRI, data/ride_delays.csv), in N_SEEDS
  draws shared by all candidates of one network trip by trip (common random numbers);
- the rider sees the actual departures (as with live arrival times) and needs TRANSFER_MIN minutes at a
  transfer, so tight connections are missed when the first bus is late;
- a trip that walking does faster counts its walk.
One scan per (home, leaving time, draw) gives the arrivals at all of that home's destinations.

Check: leaving times the search did not see (HOLDOUT_LEAVE) and N_SEEDS_CHECK new delay draws, all area x
place pairs, for today / today retimed / the plan / the plan retimed; also the perceived time (walk and wait
x1.6, +5 min a transfer) on new draws; and the buses needed (vehicle blocks, scripts/blocking.py).

Usage: PYTHONPATH=.:scripts python3 analysis/timetable_offsets.py [N_RANDOM]   Output: data/timetable_offsets.json
"""
import json
import math
import random
import sys

import numpy as np
import pandas as pd

import blocking as BL
import optimize as O
import shift_trips as SHT
from eilat import demand as Dm
from eilat import params as P
from eilat.evaluate import walk_min
from eilat.speeds import Speeds
from eilat.timetable import DelaySampler, Network

PLAN, SEASON, LAST = "full_peak-3_warm", "winter", 23
N_RANDOM = int(sys.argv[1]) if len(sys.argv) > 1 else 300
SWEEPS, GRID = 2, 8
TRANSFER_MIN = 2.0
N_SEEDS, N_SEEDS_CHECK, N_SEEDS_PERCEIVED = 4, 10, 3
TRAIN_LEAVE = range(7 * 60, 21 * 60, 60)          # 07:00, 08:00, ... 20:00
HOLDOUT_LEAVE = range(7 * 60 + 23, 21 * 60, 30)   # 07:23, 07:53, ... (not seen by the search)
random.seed(7)
SPEEDS = Speeds()
G = "data/gtfs_eilat/"


def pattern_trips(pats, phases, shift, keys=None, speeds=None):
    """Stop times (trip_id, stop_id, stop_sequence, t) and trip ends for the plan's non-school lines, each
    trip run at the measured segment times of its hours; keys gets each trip's stable name
    (pattern|period|departure number) for shared random delays."""
    rows, ends = [], []
    keys = {} if keys is None else keys
    speeds = speeds or SPEEDS
    count = {}
    for p in pats:
        ph = phases[p.name]
        for q, (a, b) in P.PERIODS.items():
            h = p.headway.get(q, math.inf)
            if not math.isfinite(h):
                continue
            keep = [i for i, s in enumerate(p.stops) if not (s in p.skip and 0 < i < len(p.stops) - 1)]
            starts = list(np.arange(a * 60 + ph * h, min(b, LAST) * 60, h))
            if q == "19-24":
                starts += [r.start for r in shift.itertuples() if r.pattern == p.name]
            for t0 in starts:
                cum = speeds.pattern_run(p, t0)
                tid = f"{p.name}@{t0:.1f}"
                n = count[(p.name, q)] = count.get((p.name, q), -1) + 1
                keys[tid] = f"{p.name}|{q}|{n}"
                rows += [(tid, p.stops[i], k, cum[i]) for k, i in enumerate(keep)]
                ends.append(dict(line=p.line, start=t0, end=float(cum[-1]), o=p.stops[0], d=p.stops[-1]))
    return rows, ends


def timed(rows_by_trip, scale_at):
    """{trip_id: (stops, printed minutes)} -> (trip_id, stop_id, stop_sequence, t) rows, run with the measured
    segment times of their hours (an unmeasured segment: printed x scale_at(clock))."""
    out = []
    for tid, (s, t) in rows_by_trip.items():
        d = np.diff(t)
        tt = SPEEDS.run(list(s), t[0], lambda i, c, d=d: d[i] * scale_at(c))
        out += [(tid, int(s[k]), k + 1, float(tt[k])) for k in range(len(s))]
    return out


class Base:
    """Shared by both networks: the trips to plan (areas x places), the delays, the scores."""

    def __init__(self):
        self.stops = pd.read_csv("data/stops_all.csv").drop_duplicates("stop_id").set_index("stop_id")
        self.sampler = DelaySampler()
        self.foot = None
        self._memo = {}
        tr = pd.read_csv(G + "trips.csv").merge(pd.read_csv(G + "routes.csv")[["route_id", "route_short_name"]], on="route_id")
        tr["line"] = tr.route_short_name.astype(str)
        st = pd.read_csv(G + "stop_times.csv").sort_values(["trip_id", "stop_sequence"])
        st = st.merge(tr[["trip_id", "line", "direction_id"]], on="trip_id")
        self.gtfs = st
        sch = st[st.line.isin(BL.SCHOOL)]
        self.school = timed({f"s{t}": (g.stop_id.values, g.dep.values / 60) for t, g in sch.groupby("trip_id")},
                            SPEEDS.city_factor)
        self.school_line = {f"s{t}": ln for t, ln in zip(sch.trip_id, sch.line, strict=True)}
        m = O.Problem("full").m
        pts = m.pts
        homes = []
        for _, g in pts.iloc[m.homes].groupby("area"):
            c = g[["lat", "lon"]].mean()
            h = g.index[np.argmin((g.lat - c.lat) ** 2 + (g.lon - c.lon) ** 2)]
            homes.append(((float(pts.lat[h]), float(pts.lon[h])), float(g["pop"].sum())))
        att = Dm.ATTRACTORS
        places = [(float(att.lat[i]), float(att.lon[i])) for i in range(len(att))]
        self.od = [(o, d, w, float(walk_min(o[0], o[1], d[0], d[1]))) for o, w in homes for d in places
                   if walk_min(o[0], o[1], d[0], d[1]) >= 15]

    def make(self, rows, line, keys):
        df = pd.DataFrame(rows + self.school, columns=["trip_id", "stop_id", "stop_sequence", "t"])
        line = dict(line); line.update(self.school_line)
        net = Network(df, line, self.stops, 1.0, self.foot)
        self.foot = net.foot
        return net, keys

    def score(self, phases, leave, od=None, seeds=range(N_SEEDS)):
        """Mean door-to-door minutes. One scan per (home, leaving time, delay draw) gives the arrivals at all
        of that home's destinations, and stops once walking would be faster for all of them."""
        key = (tuple(sorted(phases.items())), tuple(leave), id(od), tuple(seeds))
        if key in self._memo:
            return self._memo[key]
        net, keys = self.network(phases)
        by_home = {}
        for o, d, w, wd in (od or self.od):
            by_home.setdefault(o, []).append((d, w, wd))
        tot = wsum = 0.0
        for seed in seeds:
            real = net.realize(self.sampler, seed, keys)
            for o, ds in by_home.items():
                horizon = max(wd for _, _, wd in ds)
                for t0 in leave:
                    arr = real.arrivals(o[0], o[1], [d for d, _, _ in ds], t0, TRANSFER_MIN, horizon)
                    for (d, w, wd), a in zip(ds, arr, strict=True):
                        tt = wd if not np.isfinite(a) else min(a - t0, wd)
                        tot += w * tt; wsum += w
        self._memo[key] = tot / wsum
        return tot / wsum

    def perceived(self, phases, leave, seeds):
        """Mean perceived minutes: in-vehicle + 1.6 x (walk + wait) + 5 a transfer; the rider takes the
        earliest arrival, or walks if that is faster. (The wait includes the wait for the first bus, the
        rider leaving home at the given time.)"""
        net, keys = self.network(phases)
        tot = wsum = 0.0
        for seed in seeds:
            real = net.realize(self.sampler, seed, keys)
            for o, d, w, wd in self.od:
                for t0 in leave:
                    r = real.plan(o[0], o[1], d[0], d[1], t0, TRANSFER_MIN)
                    if r is None or r["arrive"] - t0 >= wd:
                        v = P.W_WALK * wd
                    else:
                        rides = [g for g in r["legs"] if g[0] == "ride"]
                        ivt = sum(g[5] - g[3] for g in rides)
                        walk = sum(g[1] for g in r["legs"] if g[0] == "walk")
                        wait = (r["arrive"] - t0) - ivt - walk
                        v = ivt + P.W_WALK * walk + P.W_WAIT * wait + P.TRANSFER_PENALTY * (len(rides) - 1)
                    tot += w * v; wsum += w
        return tot / wsum

    def buses(self, phases):
        net, _ = self.network(phases)
        trips = pd.DataFrame([dict(line=net.line.get(tid, ""), start=t[0], end=t[-1], o=int(s[0]), d=int(s[-1]))
                              for tid, (s, t) in net.trips.items()])
        trips = trips[trips.o.isin(self.stops.index) & trips.d.isin(self.stops.index)]
        _, _, blocks = BL.block(trips, self.stops)
        return len(blocks)


class PlanNet(Base):
    def __init__(self):
        super().__init__()
        net = BL.option_net(PLAN, SEASON)
        self.pats = [p for p in net if p.line not in BL.SCHOOL]
        self.shift = SHT.shift_trips(net, SHT.hotel_stops())
        self.names = [p.name for p in self.pats]
        self.start = {p.name: (0.5 if "/1" in p.name else 0.0) for p in self.pats}

    def network(self, phases):
        keys = {}
        rows, _ = pattern_trips(self.pats, phases, self.shift, keys)
        return self.make(rows, {r[0]: r[0].split("/")[0] for r in rows}, keys)


class TodayNet(Base):
    def __init__(self):
        super().__init__()
        st = self.gtfs[~self.gtfs.line.isin(BL.SCHOOL)]
        self.trips, self.group = {}, {}
        for tid, g in st.groupby("trip_id"):
            self.trips[tid] = (g.stop_id.values, g.dep.values / 60)
            self.group[tid] = f"{g.line.iloc[0]}/{g.direction_id.iloc[0]}"
        self.line = {tid: n.split("/")[0] for tid, n in self.group.items()}
        self.names = sorted(set(self.group.values()))
        # typical headway of each line direction: the median gap between departures, 07:00-19:00
        self.h = {}
        for n in self.names:
            t0 = np.sort([t[0] for tid, (s, t) in self.trips.items() if self.group[tid] == n])
            gaps = np.diff(t0[(t0 >= 7 * 60) & (t0 < 19 * 60)])
            self.h[n] = float(np.median(gaps)) if len(gaps) else 60.0
        self.start = {n: 0.5 for n in self.names}

    def network(self, phases):
        moved = {tid: (s, t + (phases[self.group[tid]] - 0.5) * self.h[self.group[tid]])
                 for tid, (s, t) in self.trips.items()}
        return self.make(timed(moved, SPEEDS.city_factor), self.line, None)


def search(S, train_od, label):
    f = lambda ph: S.score(ph, TRAIN_LEAVE, train_od)  # noqa: E731
    best, best_s = dict(S.start), f(S.start)
    print(f"[{label}] start (train sample): {best_s:.2f}", flush=True)
    rng = random.Random(11)
    for k in range(N_RANDOM):
        ph = {n: rng.random() for n in S.names}
        s = f(ph)
        if s < best_s:
            best, best_s = ph, s
            print(f"[{label}]   MC {k}: {s:.2f}", flush=True)
    for sw in range(SWEEPS):
        for n in S.names:
            for g in range(GRID):
                ph = dict(best); ph[n] = g / GRID
                s = f(ph)
                if s < best_s - 1e-6:
                    best, best_s = ph, s
        print(f"[{label}] sweep {sw}: {best_s:.2f}", flush=True)
    return best


def main():
    nets = {"today": TodayNet(), "plan": PlanNet()}
    nets["plan"].foot = nets["today"].network(nets["today"].start)[0].foot
    train_od = random.sample(nets["plan"].od, min(60, len(nets["plan"].od)))   # the search scores on a sample
    best = {k: search(S, train_od, k) for k, S in nets.items()}
    check = range(100, 100 + N_SEEDS_CHECK)                                     # delay draws not seen
    pcheck = range(200, 200 + N_SEEDS_PERCEIVED)
    pleave = range(7 * 60 + 23, 21 * 60, 60)
    res = {}
    for k, S in nets.items():
        for label, ph in ((k, S.start), (k + "_retimed", best[k])):
            res[label] = dict(train=round(S.score(ph, TRAIN_LEAVE, train_od), 2),
                              holdout=round(S.score(ph, HOLDOUT_LEAVE, None, check), 2),
                              perceived=round(S.perceived(ph, pleave, pcheck), 2),
                              buses=S.buses(ph))
            print(label, res[label], flush=True)
    res["phases"] = {k: {n: round(v, 3) for n, v in best[k].items()} for k in nets}
    res["setup"] = dict(transfer_min=TRANSFER_MIN, seeds_search=N_SEEDS, seeds_check=N_SEEDS_CHECK, train_od=len(train_od),
                        all_od=len(nets["plan"].od), n_random=N_RANDOM, sweeps=SWEEPS, grid=GRID)
    json.dump(res, open("data/timetable_offsets.json", "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
