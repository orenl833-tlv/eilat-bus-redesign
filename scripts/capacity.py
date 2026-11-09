"""Will the buses be overfull? Passengers on board at the busiest point of each line, per bus, per period.

load on a segment (riders per period, from the assignment) / period hours = riders per hour on that segment;
x PEAK_HOUR_FACTOR for the busiest hour within the period; / buses per hour (60 / headway) = riders per bus.
Compared with a standard 12 m city bus: ~85 on board full (seated + standing), ~65 comfortable.

Usage: PYTHONPATH=.:scripts python3 scripts/capacity.py   Output: data/capacity.csv, data/capacity_summary.csv
"""
import json
import math
import os

import numpy as np
import pandas as pd

import optimize as O
from eilat import demand as D
from eilat import params as P

CAP_FULL, CAP_COMFORT = 85, 65
PEAK_HOUR_FACTOR = 1.5   # assumption; 2.0 also reported
TAGS = ["today", "keep", "full_warm", "full_peak-3_warm"]


def nets_for(prob, tag):
    if tag == "today":
        return {s: prob.base for s in P.SEASONS}
    f = f"data/opt_{tag}_seasonal.json"
    if os.path.exists(f):
        sr = json.load(open(f))
        return {s: prob.network({k: {q: (h if h is not None else math.inf) for q, h in v.items()} for k, v in sr[s].items()})
                for s in P.SEASONS}
    raw = json.load(open(f"data/opt_{tag}.json"))
    st = {k: {q: (h if h is not None else math.inf) for q, h in v.items()} for k, v in raw.items()}
    return {s: prob.network(st) for s in P.SEASONS}


def main():
    rows = []
    for tag in TAGS:
        mode = "keep" if tag == "keep" else "full"
        prob = O.Problem(mode, -3 if "peak-3" in tag else 0)
        nets = nets_for(prob, tag)
        for s in P.SEASONS:
            for v, K in (("A", prob.cal["K"]), ("B", prob.cal["K_prior"])):
                r = prob.m.run(nets[s], s, K=K, track=True, **prob.kw)
                for q, (a, b) in P.PERIODS.items():
                    for k, pt in enumerate(nets[s]):
                        h = pt.headway.get(q, math.inf)
                        if not math.isfinite(h):
                            continue
                        ld = r["load"][q][k]
                        per_hour = ld.max() / (b - a)
                        per_bus = per_hour / (60 / h)
                        rows.append(dict(option=tag, season=s, calib=v, period=q, line=pt.name, headway=h,
                                         riders_per_hour_peak_segment=round(per_hour, 1),
                                         per_bus_avg=round(per_bus, 1), per_bus_peak=round(per_bus * PEAK_HOUR_FACTOR, 1),
                                         per_bus_peak2=round(per_bus * 2.0, 1)))
        print(tag, "done", flush=True)
    t = pd.DataFrame(rows); t.to_csv("data/capacity.csv", index=False)
    g = t.groupby(["option"]).agg(max_per_bus_peak=("per_bus_peak", "max"), max_per_bus_peak2=("per_bus_peak2", "max"),
                                  over_comfort=("per_bus_peak", lambda x: int((x > CAP_COMFORT).sum())),
                                  over_full=("per_bus_peak", lambda x: int((x > CAP_FULL).sum())),
                                  over_full_at_2x=("per_bus_peak2", lambda x: int((x > CAP_FULL).sum())))
    g.to_csv("data/capacity_summary.csv")
    print(g.to_string())
    print("\nbusiest line-periods:")
    print(t.sort_values("per_bus_peak", ascending=False).head(15).to_string(index=False))


if __name__ == "__main__":
    main()
