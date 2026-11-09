"""Future scenario: Star Eilat terminal plus the two planned districts (old airport, Shifolei HaHar).

1. Bus demand growth on today's network (future vs today's demand): the budget should grow by about as much.
2. Proposals vs today's network under future demand, per season and calibration.
3. How far the new districts are from a bus stop (they get no new stops in this model: agreed, existing stops only).

Usage: PYTHONPATH=.:scripts python3 scripts/future.py tag [tag ...]   Output: data/future.json
"""
import json
import math
import os
import sys

import numpy as np


def run(tags, future):
    os.environ["EILAT_FUTURE"] = "1" if future else "0"
    import importlib

    import optimize as O
    from eilat import demand as D
    importlib.reload(D)
    from eilat import model as M
    importlib.reload(M); importlib.reload(O)
    from eilat import params as P
    prob = O.Problem("full")
    out = {}
    trips_today = {}
    for s in P.SEASONS:
        r = prob.m.run(prob.base, s, K=prob.cal["K"], track=False, **prob.kw)
        trips_today[s] = {v: sum(K[p] * r["trips"][p] for p in D.PURPOSES) for v, K in (("A", prob.cal["K"]), ("B", prob.cal["K_prior"]))}
    out["bus_trips_today_network"] = trips_today
    for tag in tags:
        raw = json.load(open(f"data/opt_{tag}.json"))
        st = {k: {q: (h if h is not None else math.inf) for q, h in v.items()} for k, v in raw.items()}
        for k in prob.state0:
            st.setdefault(k, {q: math.inf for q in P.PERIODS})
        st = {k: v for k, v in st.items() if k in prob.lines}
        d = prob.score(st, detail=True)
        out[tag] = dict(by=d["by"], worst_area=float(d["worst_area"]))
    if future:
        ev = prob.m.ev
        for code in (901, 902):
            idx = [i for i, h in enumerate(prob.m.homes) if prob.m.pts.area.values[h] == code]
            dmin = ev.acc[prob.m.homes[idx]].min(axis=1) * (P.WALK_KMH * 1000 / 60) / P.DETOUR
            out[f"district_{code}_nearest_stop_m"] = float(np.median(dmin))
    return out


def main():
    tags = sys.argv[1:]
    res = {"today": run(tags, False), "future": run(tags, True)}
    for s in res["today"]["bus_trips_today_network"]:
        for v in ("A", "B"):
            a = res["today"]["bus_trips_today_network"][s][v]; b = res["future"]["bus_trips_today_network"][s][v]
            print(f"{s}/{v}: bus trips today {a:,.0f} -> future {b:,.0f} ({(b / a - 1) * 100:+.0f}%)")
    for t in tags:
        print(t, "today:", {k: round(v, 3) for k, v in res["today"][t]["by"].items()})
        print(t, "future:", {k: round(v, 3) for k, v in res["future"][t]["by"].items()}, "worst area", round(res["future"][t]["worst_area"], 3))
    for k, v in res["future"].items():
        if k.startswith("district"):
            print(k, round(v))
    json.dump(res, open("data/future.json", "w"), indent=1, default=float)


if __name__ == "__main__":
    main()
