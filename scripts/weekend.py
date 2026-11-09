"""Friday and Saturday: calibrate one weekend scale, then tune each option's frequencies for both days.

- Today's Friday / Saturday networks: GTFS 13 / 14 Nov 2026 (data/gtfs_eilat_fri, _sat).
- Demand: weekday model with day-type factors (eilat/demand.py DAY_FACTORS), winter, both calibrations.
  One scale S is fitted so that Friday + Saturday boardings per line match the ridership file's
  (weekly - 5 x weekday) for 2025 Q4.
- Each option keeps its weekday line structure (winter state). Headways are tuned per day by simulated
  annealing under today's same-day budget (buses at once, bus-hours, model formula). Service is allowed
  only in periods that have service today on that day (Shabbat hours are a policy, not a model choice).

Usage: PYTHONPATH=.:scripts python3 scripts/weekend.py   Output: data/weekend.json
"""
import copy
import json
import math
import random

import numpy as np
import pandas as pd

import optimize as O
from eilat import demand as D
from eilat import model as M
from eilat import network as N
from eilat import params as P

LINES = ["1", "2", "3", "4", "5", "6", "15", "16"]
DAYS = {"friday": "data/gtfs_eilat_fri", "saturday": "data/gtfs_eilat_sat"}
ITERS = 300


def weekend_targets():
    d = pd.read_csv("data/ridership_eilat.csv")
    d = d[(d.DestinationCityName == "אילת") & (d.year == 2025) & (d.Q.astype(str) == "Q4")]
    d["we"] = d.WeeklyPassengers - 5 * d.DailyPassengers
    return d.groupby(d.RouteName.astype(str)).we.sum().reindex(LINES)


def boardings(m, pats, K, kw):
    r = m.run(pats, "winter", K=K, track=True, **kw)
    out = pd.Series(0.0, index=LINES)
    for p in D.PURPOSES:
        for pt, x in zip(pats, r["board"][p], strict=True):
            ln = M.line_of(pt.line)
            if ln in out.index:
                out[ln] += x
    return out


def cost(m, pats, cal, kw, S):
    r = m.run(pats, "winter", K={q: 1.0 for q in D.PURPOSES}, track=False, **kw)
    return {v: S * sum(K[p] * r["cost_p"][p] for p in D.PURPOSES) for v, K in (("A", cal["K"]), ("B", cal["K_prior"]))}


def main():
    random.seed(5)
    prob = O.Problem("full")
    cal, kw, m = prob.cal, prob.kw, prob.m
    base = {d: N.from_gtfs(gdir=g) for d, g in DAYS.items()}
    # 1. calibrate the weekend scale on today's Friday + Saturday networks (calibration A)
    pred = 0
    for d in DAYS:
        D.DAY = d
        pred = pred + boardings(m, base[d], cal["K"], kw)
    y = weekend_targets()
    S = float((pred * y).sum() / (pred * pred).sum())
    fit = pd.DataFrame({"observed": y, "model": (pred * S).round(0)})
    fit["ratio"] = (fit.model / fit.observed).round(2)
    print("weekend scale", round(S, 3)); print(fit.to_string())
    out = {"scale": S, "fit": fit.reset_index().to_dict("records")}
    for tag in ["keep", "full_warm", "full_peak-3_warm"]:
        sr = json.load(open(f"data/opt_{tag}_seasonal.json"))["winter"]
        active = [k for k, v in sr.items() if any(h is not None for h in v.values())]
        out[tag] = {}
        for d, g in DAYS.items():
            D.DAY = d
            b = base[d]
            allowed = {q for q in P.PERIODS if any(math.isfinite(p.headway.get(q, math.inf)) for p in b if p.line not in O.SCHOOL)}
            bud_b, bud_h = N.fleet(b)
            budget_peak, budget_hours = max(bud_b.values()), bud_h
            c0 = cost(m, b, cal, kw, S)
            fixed = [p for p in b if p.line in O.SCHOOL]

            def net(state):
                pats = list(fixed)
                for ln, hw in state.items():
                    for p in prob.lines[ln]:
                        q = copy.copy(p); q.headway = dict(hw); pats.append(q)
                return pats

            def score(state):
                pats = net(state)
                bb, hh = N.fleet(pats)
                c = cost(m, pats, cal, kw, S)
                pen = 0.02 * max(0, max(bb.values()) - budget_peak) + 0.002 * max(0, hh - budget_hours)
                return 0.5 * (c["A"] / c0["A"] + c["B"] / c0["B"]) + pen, c, bb, hh

            # start: each active line at 30 min where today has service, else off; then anneal
            cur = {ln: {q: (30.0 if q in allowed else math.inf) for q in P.PERIODS} for ln in active}
            cur_s = score(cur)[0]; best, best_s = cur, cur_s
            for it in range(ITERS):
                s_ = copy.deepcopy(cur)
                ln = random.choice(active); q = random.choice(sorted(allowed)); h = s_[ln][q]
                i = O.LEVELS.index(h) if math.isfinite(h) else len(O.LEVELS)
                i = max(0, min(len(O.LEVELS), i + random.choice([-1, 1])))
                s_[ln][q] = O.LEVELS[i] if i < len(O.LEVELS) else math.inf
                sc = score(s_)[0]
                T = 0.003 * (1 - it / ITERS) + 1e-5
                if sc < cur_s or random.random() < math.exp(-(sc - cur_s) / T):
                    cur, cur_s = s_, sc
                    if sc < best_s:
                        best, best_s = s_, sc
            tot, c, bb, hh = score(best)
            out[tag][d] = dict(vs_today_A=round(c["A"] / c0["A"], 4), vs_today_B=round(c["B"] / c0["B"], 4),
                               peak=max(bb.values()), hours=round(hh, 1), budget_peak=budget_peak, budget_hours=round(budget_hours, 1),
                               state={k: {q: (h if math.isfinite(h) else None) for q, h in v.items()} for k, v in best.items()})
            print(tag, d, {k: v for k, v in out[tag][d].items() if k != "state"}, flush=True)
    D.DAY = "weekday"
    json.dump(out, open("data/weekend.json", "w"), indent=1)


if __name__ == "__main__":
    main()
