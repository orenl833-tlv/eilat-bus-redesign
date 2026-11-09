"""Search for a better urban network under today's fleet and bus-hour budget.

State: for every candidate line, a headway level per period (or off). Moves: one line one period up/down a
level, a line on/off, swap a line for one of its variants. Simulated annealing on

    objective = sum over seasons of (months x perceived cost / today's perceived cost), averaged over the two
    demand calibrations (A: fitted, B: leaning on the prior purpose mix)

with penalties for: more buses at once than today (any period), more bus-hours than today, any residential area
more than MAX_AREA_LOSS worse off (either calibration), and coverage below the rule or below today.
School lines (80-82) stay as they are. "moderate": only today's lines and their straightened / stop-skipping
variants; "full": also new direct lines.

Usage: PYTHONPATH=. python3 scripts/optimize.py moderate|full [iterations] [peak_budget_delta]
Outputs: data/opt_<mode>.json (best state), data/opt_<mode>_log.csv
"""
import copy
import json
import math
import random
import sys
import time

import numpy as np
import pandas as pd

from eilat import candidates as C
from eilat import demand as D
from eilat import model as M
from eilat import network as N
from eilat import params as P

LEVELS = [10, 12, 15, 20, 24, 30, 40, 60]
SCHOOL = {"80", "80א", "81", "82"}
SEASONS = list(P.SEASONS)


class Problem:
    def __init__(self, mode, peak_delta=0):
        self.keep = mode == "keep"
        mode = "moderate" if mode == "keep" else mode
        self.cal = json.load(open("data/calibration.json"))
        self.m = M.Model()
        self.base = N.from_gtfs()
        self.sg = C.StopGraph(self.base)
        self.fixed = [p for p in self.base if p.line in SCHOOL]
        self.lines = {}   # line name -> list of patterns (headways ignored; state decides)
        self.family = {}  # line -> family key (a base line and its variants share one)
        for p in self.base:
            if p.line in SCHOOL:
                continue
            self.lines.setdefault(p.line, []).append(p); self.family[p.line] = p.line
        # baseline run with tracking to know stop use
        self.kw = dict(lam=self.cal["lam"], const=self.cal["const"], car_prop=self.cal["car_prop"])
        r0 = self.m.run(self.base, "winter", K=self.cal["K"], track=True, **self.kw)
        stop_use = {self.m.ev.stops.stop_id.iloc[i]: q for i, q in r0["stop_use"].items()}
        for ln, pats in list(self.lines.items()):
            var_s, var_x = [], []
            for p in pats:
                s = C.straightened(self.sg, p)
                var_s.append(s if s is not None and s.run_min("09-12") < p.run_min("09-12") - 1 else None)
                trips = sum((b - a) * 60 / p.headway[q] for q, (a, b) in P.PERIODS.items() if math.isfinite(p.headway[q]))
                var_x.append(C.skipping(self.sg, p, stop_use, trips))
            for tag, var in (("s", var_s), ("x", var_x)):
                if any(v is not None for v in var):
                    pats_v = [v if v is not None else copy.deepcopy(p) for v, p in zip(var, pats, strict=True)]
                    for q in pats_v:
                        q.line = ln + tag
                    self.lines[ln + tag] = pats_v; self.family[ln + tag] = ln
        if mode == "full":
            a, _ = D.areas(); st = self.sg.stops
            anch = {}
            for r in a.itertuples():
                c = r.geometry.representative_point()
                d = np.hypot(st.stop_lat - c.y, (st.stop_lon - c.x) * 0.87)
                anch[int(r.stat11)] = int(st.stop_id.iloc[int(d.argmin())])
            for pair in C.new_lines(self.sg, anch):
                self.lines[pair[0].line] = pair; self.family[pair[0].line] = pair[0].line
        self.base_lines = {p.line for p in self.base if p.line not in SCHOOL}
        # today's state: base lines at their own headways (snapped to levels), variants and new lines off
        self.state0 = {}
        for ln, pats in self.lines.items():
            if ln in {p.line for p in self.base}:
                self.state0[ln] = {q: self.snap(min(p.headway[q] for p in pats)) for q in P.PERIODS}
            else:
                self.state0[ln] = {q: math.inf for q in P.PERIODS}
        # budgets from today's real network
        buses, hours = N.fleet(self.base)
        self.budget_peak = max(buses.values()) + peak_delta
        self.budget_hours = hours + (-peak_delta) * P.PEAK_BUS_IN_HOURS * 1.0   # trade buses for hours
        self.base_eval = self.raw(self.base)
        print(f"lines in pool: {len(self.lines)} | budget: {self.budget_peak} buses at once, {self.budget_hours:.0f} bus-hours")

    @staticmethod
    def snap(h):
        if not math.isfinite(h) or h > 90:
            return math.inf
        return min(LEVELS, key=lambda x: abs(x - h))

    def network(self, state):
        pats = list(self.fixed)
        for ln, hw in state.items():
            if all(not math.isfinite(h) for h in hw.values()):
                continue
            for p in self.lines[ln]:
                q = copy.copy(p); q.headway = dict(hw); pats.append(q)
        return pats

    def raw(self, pats):
        """Perceived cost per season and calibration, and per area (calibration A and B)."""
        out = {}
        for s in SEASONS:
            r = self.m.run(pats, s, K={q: 1.0 for q in D.PURPOSES}, track=False, **self.kw)
            for v, K in (("A", self.cal["K"]), ("B", self.cal["K_prior"])):
                cost = sum(K[p] * r["cost_p"][p] for p in D.PURPOSES)
                hc = sum(K[p] * r["home_cost"][p] for p in D.PURPOSES if p != "tourist")
                ht = sum(K[p] * r["home_trips"][p] for p in D.PURPOSES if p != "tourist")
                area = pd.Series(hc).groupby(self.m.pts.area.values[self.m.homes]).sum() / \
                    pd.Series(ht).groupby(self.m.pts.area.values[self.m.homes]).sum()
                out[(s, v)] = (cost, area)
        return out

    def coverage(self, pats):
        """Per area: share of its points within COVERAGE_STOP_M of a stop served at least every 30 min in daytime."""
        ok_stops = set()
        for p in pats:
            if all(p.headway.get(q, math.inf) <= P.COVERAGE_HEADWAY_MIN for q in ("09-12", "12-15", "15-19")):
                ok_stops |= {s for s in p.stops if s not in p.skip}
        ev = self.m.ev
        cols = [ev.sid[s] for s in ok_stops if s in ev.sid]
        d = ev.acc[self.m.homes][:, cols].min(axis=1) * (P.WALK_KMH * 1000 / 60) if cols else np.full(len(self.m.homes), 1e9)
        within = pd.Series(d <= P.COVERAGE_STOP_M * P.DETOUR)
        return within.groupby(self.m.pts.area.values[self.m.homes]).mean()

    def protected_lost(self, pats):
        """Protected stops (luggage, hospital, campus) served by today's network all day that no line stops at."""
        day = ("09-12", "12-15", "15-19")
        def served(net):
            out = set()
            for p in net:
                if all(math.isfinite(p.headway.get(q, math.inf)) for q in day):
                    out |= {s for s in p.stops if s not in p.skip}
            return out
        if not hasattr(self, "_prot_today"):
            self._prot_today = served(self.base) & self.sg.protected
        return len(self._prot_today - served(pats))

    @staticmethod
    def violations(state):
        """Usable-network rules: a running line serves 09-19 at least hourly; adjacent periods differ by <= 2x."""
        n = 0
        order = list(P.PERIODS)
        for ln, hw in state.items():
            if all(not math.isfinite(h) for h in hw.values()):
                continue
            n += sum(1 for q in ("09-12", "12-15", "15-19") if not hw[q] <= 60)
            for a, b in zip(order[:-1], order[1:], strict=True):
                ha, hb = hw[a], hw[b]
                if math.isfinite(ha) and math.isfinite(hb) and max(ha, hb) / min(ha, hb) > 2.0001:
                    n += 1
        return n

    def score(self, state, detail=False):
        pats = self.network(state)
        buses, hours = N.fleet(pats)
        pen = 0.0
        pen += 0.02 * max(0, max(buses.values()) - self.budget_peak)
        pen += 0.002 * max(0, hours - self.budget_hours)
        ev = self.raw(pats)
        obj = 0.0; worst = 1.0
        for s in SEASONS:
            w = P.SEASONS[s]["months"] / 12
            for v in ("A", "B"):
                c, area = ev[(s, v)]; c0, area0 = self.base_eval[(s, v)]
                obj += w * 0.5 * c / c0
                rel = (area / area0).max()
                worst = max(worst, rel)
                pen += 0.05 * max(0, rel - (1 + P.MAX_AREA_LOSS))
        pen += 0.01 * self.violations(state)
        pen += 0.01 * self.protected_lost(pats)
        if self.keep:   # conservative option: every line of today survives in some form
            fams = {}
            for ln, hw in state.items():
                fams.setdefault(self.family[ln], False)
                fams[self.family[ln]] |= any(math.isfinite(h) for h in hw.values())
            pen += 0.02 * sum(1 for f, on in fams.items() if not on and f in self.base_lines)
        cov, cov0 = self.coverage(pats), self.coverage(self.base)
        pen += 0.01 * float(np.maximum(0, np.minimum(0.5, cov0) - cov).sum())
        total = obj + pen
        if detail:
            return dict(total=total, obj=obj, pen=pen, buses=buses, hours=hours, worst_area=worst,
                        violations=self.violations(state), protected_lost=self.protected_lost(pats), by=({f"{s}/{v}": ev[(s, v)][0] / self.base_eval[(s, v)][0] for s in SEASONS for v in ("A", "B")}))
        return total


def neighbour(prob, state):
    s = copy.deepcopy(state)
    ln = random.choice(list(s))
    r = random.random()
    on = any(math.isfinite(h) for h in s[ln].values())
    if r < 0.6 and on:      # one period one level
        q = random.choice(list(P.PERIODS)); h = s[ln][q]
        i = LEVELS.index(h) if math.isfinite(h) else len(LEVELS)
        i = max(0, min(len(LEVELS), i + random.choice([-1, 1])))
        s[ln][q] = LEVELS[i] if i < len(LEVELS) else math.inf
    elif r < 0.8:           # swap within a family: move this line's headways to a sibling
        fam = [x for x in s if prob.family[x] == prob.family[ln] and x != ln]
        if fam and on:
            other = random.choice(fam)
            s[other], s[ln] = s[ln], {q: math.inf for q in P.PERIODS}
    else:                   # on/off
        if on:
            s[ln] = {q: math.inf for q in P.PERIODS}
        else:
            s[ln] = {q: 20 if q != "19-24" else 30 for q in P.PERIODS}
    return s


def main():
    mode = sys.argv[1]; iters = int(sys.argv[2]) if len(sys.argv) > 2 else 1500
    peak_delta = int(sys.argv[3]) if len(sys.argv) > 3 else 0
    tag = f"{mode}" + (f"_peak{peak_delta:+d}" if peak_delta else "")
    import os
    seed = int(os.environ.get("SEED", "1"))
    random.seed(seed)
    if seed != 1:
        tag += f"_seed{seed}"
    prob = Problem(mode, peak_delta)
    cur = prob.state0
    if len(sys.argv) > 4:   # warm start from another run's best (lines missing from this pool are dropped)
        raw = json.load(open(sys.argv[4]))
        cur = dict(prob.state0)
        for k, v in raw.items():
            if k in cur:
                cur[k] = {q: (h if h is not None else math.inf) for q, h in v.items()}
        tag += "_warm"
    cur_s = prob.score(cur); best, best_s = cur, cur_s
    print("start", prob.score(cur, detail=True))
    log = []; t0 = time.time(); T0 = 0.004
    for it in range(iters):
        T = T0 * (1 - it / iters) + 1e-5
        cand = neighbour(prob, cur); s = prob.score(cand)
        if s < cur_s or random.random() < math.exp(-(s - cur_s) / T):
            cur, cur_s = cand, s
            if s < best_s:
                best, best_s = cand, s
        log.append(dict(it=it, cur=cur_s, best=best_s))
        if it % 50 == 0:
            print(f"{it} cur {cur_s:.4f} best {best_s:.4f} ({time.time() - t0:.0f}s)", flush=True)
            json.dump({k: {q: (h if math.isfinite(h) else None) for q, h in v.items()} for k, v in best.items()},
                      open(f"data/opt_{tag}.json", "w"), indent=0)
    pd.DataFrame(log).to_csv(f"data/opt_{tag}_log.csv", index=False)
    json.dump({k: {q: (h if math.isfinite(h) else None) for q, h in v.items()} for k, v in best.items()},
              open(f"data/opt_{tag}.json", "w"), indent=0)
    print("best", prob.score(best, detail=True))


if __name__ == "__main__":
    main()
