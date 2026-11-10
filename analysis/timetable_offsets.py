"""Timing the lines against each other: Monte Carlo search over departure phases (winter weekday, the plan).

Each line pattern's departures in a period are a*60 + phase*h, h its headway (the export uses phase 0 for one
direction and 0.5 for the other). The phase per pattern is searched to shorten door-to-door trips:
1. Monte Carlo: N_RANDOM random phase vectors, each scored on a training sample of trips;
2. then coordinate refinement: each pattern's phase tried on a grid, keeping the best, for SWEEPS sweeps.
Score = mean door-to-door minutes (arrival - leaving home) over areas x key places x leaving times, weighted
by the area's residents, planned on the timetable as buses really run:
- each trip runs every street segment in the time measured by GPS at that hour (eilat/speeds.py);
- every trip is delayed as a real trip of its line and hour was (SIRI, data/ride_delays.csv), in N_SEEDS
  draws shared by all candidates trip by trip (common random numbers);
- the rider sees the actual departures (as with live arrival times) and needs TRANSFER_MIN minutes at a
  transfer, so tight connections are missed when the first bus is late;
- a trip that walking does faster counts its walk.
The headways, evening end (23:00), shift-change trips and school trips are unchanged.

The result is checked on a holdout of leaving times the search did not see, and the buses needed (vehicle
blocks, scripts/blocking.py) are recounted so the fleet does not grow.

Usage: PYTHONPATH=.:scripts python3 analysis/timetable_offsets.py   Output: data/timetable_offsets.json
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
N_SEEDS, N_SEEDS_CHECK = 4, 10
TRAIN_LEAVE = range(7 * 60, 21 * 60, 60)          # 07:00, 08:00, ... 20:00
HOLDOUT_LEAVE = range(7 * 60 + 23, 21 * 60, 30)   # 07:23, 07:53, ... (not seen by the search)
random.seed(7)
SPEEDS = Speeds()


def pattern_trips(pats, phases, shift, keys=None, speeds=None):
    """Stop times (trip_id, stop_id, stop_sequence, t) and trip ends for the non-school lines, each trip run at
    the measured segment times of its hours; keys gets each trip's stable name (pattern|period|departure
    number) for shared random delays."""
    rows, ends = [], []
    keys = {} if keys is None else keys
    speeds = speeds or SPEEDS
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
                cum = speeds.pattern_run(p, t0) - t0
                tid = f"{p.name}@{t0:.1f}"
                keys[tid] = f"{p.name}|{q}|{len([1 for x in keys.values() if x.startswith(p.name + '|' + q + '|')])}"
                rows += [(tid, p.stops[i], k, t0 + cum[i]) for k, i in enumerate(keep)]
                ends.append(dict(line=p.line, start=t0, end=t0 + cum[-1], o=p.stops[0], d=p.stops[-1]))
    return rows, ends


class Scenario:
    def __init__(self):
        self.stops = pd.read_csv("data/stops_all.csv").drop_duplicates("stop_id").set_index("stop_id")
        self.sampler = DelaySampler()
        self.foot = None
        net = BL.option_net(PLAN, SEASON)
        self.pats = [p for p in net if p.line not in BL.SCHOOL]
        self.shift = SHT.shift_trips(net, SHT.hotel_stops())
        g = "data/gtfs_eilat/"
        tr = pd.read_csv(g + "trips.csv").merge(pd.read_csv(g + "routes.csv")[["route_id", "route_short_name"]], on="route_id")
        tr = tr[tr.route_short_name.astype(str).isin(BL.SCHOOL)]
        st = pd.read_csv(g + "stop_times.csv"); st = st[st.trip_id.isin(tr.trip_id)]
        self.school = [(f"s{r.trip_id}", r.stop_id, r.stop_sequence, r.dep / 60) for r in st.itertuples()]
        self.school_line = {f"s{t}": str(n) for t, n in zip(tr.trip_id, tr.route_short_name, strict=True)}
        m = O.Problem("full").m
        pts = m.pts
        self.homes = []
        for _, g in pts.iloc[m.homes].groupby("area"):
            c = g[["lat", "lon"]].mean()
            h = g.index[np.argmin((g.lat - c.lat) ** 2 + (g.lon - c.lon) ** 2)]
            self.homes.append(((float(pts.lat[h]), float(pts.lon[h])), float(g["pop"].sum())))
        att = Dm.ATTRACTORS
        self.places = [(float(att.lat[i]), float(att.lon[i])) for i in range(len(att))]
        self.od = [(o, d, w, float(walk_min(o[0], o[1], d[0], d[1]))) for o, w in self.homes for d in self.places
                   if walk_min(o[0], o[1], d[0], d[1]) >= 15]

    def network(self, phases):
        keys = {}
        rows, _ = pattern_trips(self.pats, phases, self.shift, keys)
        df = pd.DataFrame(rows + self.school, columns=["trip_id", "stop_id", "stop_sequence", "t"])
        line = {tid: tid.split("/")[0] for tid in df.trip_id.unique()}
        line.update(self.school_line)
        net = Network(df, line, self.stops, 1.0, self.foot)
        self.foot = net.foot
        return net, keys

    def score(self, phases, leave, od=None, seeds=range(N_SEEDS), net=None):
        net, keys = net if net is not None else self.network(phases)
        tot = wsum = 0.0
        for seed in seeds:
            real = net.realize(self.sampler, seed, keys)
            for o, d, w, wd in (od or self.od):
                for t0 in leave:
                    r = real.plan(o[0], o[1], d[0], d[1], t0, TRANSFER_MIN)
                    tt = wd if r is None else min(r["arrive"] - t0, wd)
                    tot += w * tt; wsum += w
        return tot / wsum


def main():
    S = Scenario()
    names = [p.name for p in S.pats]
    base = {p.name: (0.5 if "/1" in p.name else 0.0) for p in S.pats}
    train_od = random.sample(S.od, min(60, len(S.od)))       # the search scores on a sample, for speed
    f = lambda ph: S.score(ph, TRAIN_LEAVE, train_od)  # noqa: E731
    best, best_s = dict(base), f(base)
    print("baseline (train sample):", round(best_s, 2), flush=True)
    for k in range(N_RANDOM):
        ph = {n: random.random() for n in names}
        s = f(ph)
        if s < best_s:
            best, best_s = ph, s
            print(f"  MC {k}: {s:.2f}", flush=True)
    for sw in range(SWEEPS):
        for n in names:
            for g in range(GRID):
                ph = dict(best); ph[n] = g / GRID
                s = f(ph)
                if s < best_s - 1e-6:
                    best, best_s = ph, s
        print(f"sweep {sw}: {best_s:.2f}", flush=True)
    res = {}
    check = range(100, 100 + N_SEEDS_CHECK)                    # delay draws the search did not see
    today = Network.today("data/gtfs_eilat/", S.stops, SPEEDS, S.foot)
    res["today"] = dict(holdout=round(S.score(None, HOLDOUT_LEAVE, seeds=check, net=(today, None)), 2))
    print("today", res["today"], flush=True)
    for label, ph in (("baseline", base), ("tuned", best)):
        res[label] = dict(train=round(S.score(ph, TRAIN_LEAVE), 2), holdout=round(S.score(ph, HOLDOUT_LEAVE, seeds=check), 2))
        _, ends = pattern_trips(S.pats, ph, S.shift)
        trips = pd.concat([pd.DataFrame(ends), BL.trips_today()[lambda x: x.line.isin(BL.SCHOOL)]], ignore_index=True)
        st = S.stops
        trips = trips[trips.o.isin(st.index) & trips.d.isin(st.index)]
        _, peak, blocks = BL.block(trips, st)
        res[label]["buses"] = len(blocks)
        print(label, res[label], flush=True)
    res["phases"] = {n: round(v, 3) for n, v in best.items()}
    json.dump(res, open("data/timetable_offsets.json", "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
