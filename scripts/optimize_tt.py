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
import random
import sys
import time

import numpy as np
import pandas as pd

import optimize as O
import timetable_offsets as T
from eilat import network as EN
from eilat import params as P

HOURS = range(6, 23)
HALF = {6, 21, 22}
PER_HOUR = 2
N_SEEDS = 2
T0 = 0.004


def leave_times(o, which):
    rng = random.Random(f"{which}|{o[0]:.6f}|{o[1]:.6f}")
    return [(h * 60 + rng.random() * 60, 0.5 if h in HALF else 1.0) for h in HOURS for _ in range(PER_HOUR)]


class TT(T.Base):
    """Timetable scoring of a candidate network (a list of patterns) and of today's real timetable."""

    def __init__(self):
        super().__init__()
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
                ds = self.by_home[o]
                horizon = max(wd for _, _, wd in ds)
                for t0, wh in leave_times(o, which):
                    arr = real.arrivals(o[0], o[1], [d for d, _, _ in ds], t0, T.TRANSFER_MIN, horizon)
                    for (d, w, wd), a in zip(ds, arr, strict=True):
                        tt = wd if not np.isfinite(a) else min(a - t0, wd)
                        tot[o] += wh * w * tt; wt[o] += wh * w
        home = {o: tot[o] / wt[o] for o in self.homes}
        overall = sum(tot.values()) / sum(wt.values())
        return home, overall


class Search:
    def __init__(self, peak_delta=0):
        self.prob = O.Problem("full", peak_delta)
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
    cur_s = S.score(cur); best, best_s = cur, cur_s
    print("start", S.score(cur, detail=True), flush=True)
    log = []; t0 = time.time()
    for it in range(iters):
        T_ = T0 * (1 - it / iters) + 1e-5
        cand = O.neighbour(S.prob, cur); s = S.score(cand)
        if s < cur_s or random.random() < math.exp(-(s - cur_s) / T_):
            cur, cur_s = cand, s
            if s < best_s:
                best, best_s = cand, s
        log.append(dict(it=it, cur=cur_s, best=best_s))
        if it % 25 == 0:
            print(f"{it} cur {cur_s:.4f} best {best_s:.4f} ({time.time() - t0:.0f}s)", flush=True)
            dump(best, f"data/{tag}.json")
    pd.DataFrame(log).to_csv(f"data/{tag}_log.csv", index=False)
    dump(best, f"data/{tag}.json")
    print("best", S.score(best, detail=True), flush=True)


if __name__ == "__main__":
    main()
