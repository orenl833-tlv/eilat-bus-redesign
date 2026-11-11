"""Network search scored on the timetable, as buses really run (instead of the frequency-based model).

Same search space, moves and rules as scripts/optimize.py (the pool of today's lines, their straightened and
stop-skipping variants and new direct lines; headway levels per period; fleet and bus-hour budgets, protected
stops, coverage, usable timetables), but each candidate network is turned into a timetable and planned:
- trips: each area's centre to each key place at least 15 minutes' walk away, weighted by the area's residents
  (analysis/timetable_offsets.py);
- leaving home at random times, PER_HOUR in every hour HOURS (06:00-22:59; 06, 21 and 22 count half);
- street segments at the GPS-measured time of that hour and direction; every trip delayed as a real trip of
  its line, direction and hour was, N_SEEDS draws shared trip by trip by all candidates; the rider sees the
  actual departures and needs 2 minutes at a transfer; walking counts when quicker;
- objective = mean door-to-door minutes / today's (today's real timetable, timed the same way);
- penalties as in optimize.py, and an area whose mean gets more than MAX_AREA_LOSS worse than today's.
Winter weekday only (one timetable per candidate); the result is checked on new leaving times and delay draws,
in perceived time too, and its buses counted from vehicle blocks (scripts/check_tt.py).

Usage: PYTHONPATH=.:scripts:analysis python3 scripts/optimize_tt.py START ITERS SEED
  START: "today" (today's lines) or a state file (e.g. data/opt_full_peak-3_warm.json).
Output: data/opt_tt_<start>_s<seed>.json (+ _log.csv)
"""
import json
import math
import os
import random
import sys
import time

import numpy as np
import pandas as pd

import optimize as O
import timetable_offsets as T
from eilat import network as EN
from eilat import demand as Dm
from eilat import model as MD
from eilat import params as P
from eilat.evaluate import walk_min
from eilat.timetable import _period

HOURS = range(6, 23)
HALF = {6, 21, 22}
PER_HOUR = 2
N_SEEDS = 2
T0 = 0.004
REPLACE_P = 0.25 if os.environ.get("MODE") == "design" else 0.0


def leave_times(o, which):
    rng = random.Random(f"{which}|{o[0]:.6f}|{o[1]:.6f}")
    return [(h * 60 + rng.random() * 60, 0.5 if h in HALF else 1.0) for h in HOURS for _ in range(PER_HOUR)]


def demand_od(season, min_walk=10.0):
    """Trips weighted by the demand model (eilat/demand.py potential), both ways: each area's centre to each key
    place and back, per purpose, by its share of bus users (car-less households weigh more) and its time
    profile; tourists from the hotels to the places and back. Returns {origin: [(dest, walk min, {period:
    weight}), ...]} for trips at least min_walk minutes' walk."""
    m = MD.Model()
    pts = m.pts
    out, prop, tour, hotel = Dm.potential(pts, season)
    homes = pts[pts.kind == "home"].reset_index(drop=True)
    att = Dm.ATTRACTORS
    places = [(float(att.lat[i]), float(att.lon[i])) for i in range(len(att))]
    per = list(P.PERIODS)
    od = {}

    def add(o, d, k, w):
        if w <= 0:
            return
        wd = float(walk_min(o[0], o[1], d[0], d[1]))
        if wd < min_walk:
            return
        lst = od.setdefault(o, {})
        e = lst.setdefault(d, [wd, {q: 0.0 for q in per}])
        e[1][per[k]] += w
    for _, g in homes.groupby("area"):
        c = g[["lat", "lon"]].mean()
        h = g.index[np.argmin((g.lat - c.lat) ** 2 + (g.lon - c.lon) ** 2)]
        o = (float(homes.lat[h]), float(homes.lon[h]))
        for p in Dm.PURPOSES:
            if p == "tourist":
                continue
            tours = (out[p][g.index] * prop[g.index][:, None]).sum(axis=0)
            for a, n in enumerate(tours):
                for k in range(len(per)):
                    add(o, places[a], k, n * Dm.PROFILE[p]["out"][k])
                    add(places[a], o, k, n * Dm.PROFILE[p]["back"][k])
    hp = places[hotel]
    for a, n in enumerate(tour):
        for k in range(len(per)):
            add(hp, places[a], k, n * Dm.PROFILE["tourist"]["out"][k])
            add(places[a], hp, k, n * Dm.PROFILE["tourist"]["back"][k])
    return {o: [(d, wd, w) for d, (wd, w) in ds.items()] for o, ds in od.items()}


def hours_in(q):
    a, b = P.PERIODS[q]
    return len([h for h in HOURS if a <= h < b])


class TT(T.Base):
    """Timetable scoring of a candidate network (a list of patterns) and of today's real timetable.
    OD=demand in the environment: trips weighted by the demand model, season SEASON (default winter)."""

    def __init__(self):
        super().__init__()
        self.demand = os.environ.get("OD", "residents") == "demand"
        if self.demand:
            self.dod = demand_od(os.environ.get("SEASON", "winter"))
            self.homes = sorted(self.dod)
        else:
            self.homes = sorted({o for o, *_ in self.od})
            self.by_home = {o: [(d, w, wd) for oo, d, w, wd in self.od if oo == o] for o in self.homes}
        self.no_shift = pd.DataFrame(columns=["pattern", "start"])

    def net_of(self, pats):
        pats = [p for p in pats if p.line not in O.SCHOOL]
        phases = {p.name: (0.5 if "/1" in p.name else 0.0) for p in pats}
        keys = {}
        rows, _ = T.pattern_trips(pats, phases, self.no_shift, keys)
        tids = {r[0] for r in rows}
        line = {t: t.split("@")[0].split("/")[0] for t in tids}
        dkey = {t: T.delay_key(t.split("/")[0], t.split("/")[1][0]) for t in tids}
        return self.make(rows, line, keys, dkey)

    def per_home(self, net_keys, which="train", seeds=range(N_SEEDS)):
        """Mean door-to-door minutes per home (weighted over its places and leaving times) and overall."""
        net, keys = net_keys
        tot = {o: 0.0 for o in self.homes}; wt = {o: 0.0 for o in self.homes}
        for seed in seeds:
            real = net.realize(self.sampler, seed, keys)
            for o in self.homes:
                if self.demand:
                    ds = self.dod[o]
                    horizon = max(wd for _, wd, _ in ds)
                    for t0, _ in leave_times(o, which):
                        q = _period(t0)
                        arr = real.arrivals(o[0], o[1], [d for d, _, _ in ds], t0, T.TRANSFER_MIN, horizon)
                        for (d, wd, wq), a in zip(ds, arr, strict=True):
                            w = wq[q] / max(hours_in(q), 1) / PER_HOUR
                            tt = wd if not np.isfinite(a) else min(a - t0, wd)
                            tot[o] += w * tt; wt[o] += w
                    continue
                ds = self.by_home[o]
                horizon = max(wd for _, _, wd in ds)
                for t0, wh in leave_times(o, which):
                    arr = real.arrivals(o[0], o[1], [d for d, _, _ in ds], t0, T.TRANSFER_MIN, horizon)
                    for (d, w, wd), a in zip(ds, arr, strict=True):
                        tt = wd if not np.isfinite(a) else min(a - t0, wd)
                        tot[o] += wh * w * tt; wt[o] += wh * w
        home = {o: tot[o] / wt[o] for o in self.homes if wt[o] > 0}
        overall = sum(tot.values()) / sum(wt.values())
        return home, overall


class Search:
    def __init__(self, peak_delta=0, mode=None):
        self.prob = O.Problem(mode or os.environ.get("MODE", "full"), peak_delta)
        self.tt = TT()
        today = T.TodayNet()
        today.foot = self.tt.foot = today.network(today.start)[0].foot
        self.tt.foot = today.foot
        self.today_home, self.today = self.tt.per_home(today.network(today.start))
        print(f"today (real timetable): {self.today:.2f} min", flush=True)
        self.memo = {}

    def score(self, state, detail=False):
        key = json.dumps({k: {q: (h if math.isfinite(h) else None) for q, h in v.items()} for k, v in sorted(state.items())})
        if key in self.memo and not detail:
            return self.memo[key]
        prob = self.prob
        pats = prob.network(state)
        buses, hours = EN.fleet(pats)
        pen = 0.02 * max(0, max(buses.values()) - prob.budget_peak) + 0.002 * max(0, hours - prob.budget_hours)
        home, overall = self.tt.per_home(self.tt.net_of(pats))
        obj = overall / self.today
        worst = max(home[o] / self.today_home[o] for o in home)
        pen += 0.05 * max(0, worst - (1 + P.MAX_AREA_LOSS))
        pen += 0.01 * prob.violations(state) + 0.1 * prob.protected_lost(pats)
        cov, cov0 = prob.coverage(pats), prob.coverage(prob.base)
        pen += 0.01 * float(np.maximum(0, np.minimum(0.5, cov0) - cov).sum())
        total = obj + pen
        self.memo[key] = total
        if detail:
            return dict(total=total, obj=obj, minutes=overall, pen=pen, buses=buses, hours=hours, worst_area=worst,
                        violations=prob.violations(state), protected_lost=prob.protected_lost(pats))
        return total


def replace_move(prob, state):
    """Trade one running line for one that is off (a designed line when there are any): the new line takes the
    old one's headways, so the network stays about as costly. A single on/off move cannot do this when the
    budget is tight: adding a line alone is penalised before anything can be taken off."""
    s = dict(state)
    on = [k for k, v in s.items() if any(math.isfinite(h) for h in v.values())]
    off = [k for k in s if k not in on]
    designed = [k for k in off if k.startswith("D")]
    if not on or not off:
        return O.neighbour(prob, state)
    old = random.choice(on); new = random.choice(designed or off)
    s[new], s[old] = dict(s[old]), {q: math.inf for q in P.PERIODS}
    return s


def dump(state, path):
    json.dump({k: {q: (h if math.isfinite(h) else None) for q, h in v.items()} for k, v in state.items()},
              open(path, "w"), indent=0)


def main():
    start, iters, seed = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
    random.seed(seed)
    S = Search()
    cur = dict(S.prob.state0)
    if start != "today":
        raw = json.load(open(start))
        for k, v in raw.items():
            if k in cur:
                cur[k] = {q: (h if h is not None else math.inf) for q, h in v.items()}
    tag = f"opt_tt_{'today' if start == 'today' else start.split('opt_')[-1].replace('.json', '')}_s{seed}"
    if os.environ.get("MODE", "full") != "full":
        tag += "_" + os.environ["MODE"]
    if os.environ.get("OD", "residents") == "demand":
        tag += "_demand"
    ck = f"data/{tag}_ckpt.json"
    it0, log = 0, []
    if os.path.exists(ck):     # resume (long runs get cut off by restarts)
        c = json.load(open(ck))
        load = lambda d: {k: {q: (h if h is not None else math.inf) for q, h in v.items()} for k, v in d.items()}  # noqa: E731
        cur, best, it0, log = load(c["cur"]), load(c["best"]), c["it"], c["log"]
        random.seed(seed * 1000 + it0)
    cur_s = S.score(cur); best_s = S.score(best) if it0 else cur_s
    if not it0:
        best = cur
    print("start", it0, S.score(cur, detail=True), flush=True)
    t0 = time.time()
    enc = lambda d: {k: {q: (h if math.isfinite(h) else None) for q, h in v.items()} for k, v in d.items()}  # noqa: E731
    for it in range(it0, iters):
        T_ = T0 * (1 - it / iters) + 1e-5
        cand = replace_move(S.prob, cur) if random.random() < REPLACE_P else O.neighbour(S.prob, cur)
        s = S.score(cand)
        if s < cur_s or random.random() < math.exp(-(s - cur_s) / T_):
            cur, cur_s = cand, s
            if s < best_s:
                best, best_s = cand, s
        log.append(dict(it=it, cur=cur_s, best=best_s))
        if it % 25 == 0:
            print(f"{it} cur {cur_s:.4f} best {best_s:.4f} ({time.time() - t0:.0f}s)", flush=True)
            dump(best, f"data/{tag}.json")
            json.dump(dict(cur=enc(cur), best=enc(best), it=it + 1, log=log), open(ck, "w"))
    pd.DataFrame(log).to_csv(f"data/{tag}_log.csv", index=False)
    dump(best, f"data/{tag}.json")
    print("best", S.score(best, detail=True), flush=True)


if __name__ == "__main__":
    main()
