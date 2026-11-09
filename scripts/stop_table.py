"""Every stop that loses service in each option, for a stop-by-stop review.

Two lists per option (winter, 09:00-12:00 network):
- passed: a line passes the stop without stopping (other lines may still stop there);
- dropped: served by some line today, by no line in the option (route straightened, line merged).
For each stop: boardings + alightings today (model, calibration A, weekday), whether another line still serves
it, and the nearest stop still served with its walking distance.

Usage: PYTHONPATH=.:scripts python3 scripts/stop_table.py   Output: data/stops_<option>.csv, printed summary
"""
import json
import math

import pandas as pd

import optimize as O
from eilat import params as P
from eilat.evaluate import walk_min


def served(pats, period="09-12"):
    s = {}
    for p in pats:
        if not math.isfinite(p.headway.get(period, math.inf)):
            continue
        for x in p.stops:
            if x not in p.skip:
                s.setdefault(x, []).append(p.name)
    return s


def main():
    prob = O.Problem("full")
    st = prob.sg.stops.set_index("stop_id")
    r0 = prob.m.run(prob.base, "winter", K=prob.cal["K"], track=True, **prob.kw)
    use = {prob.m.ev.stops.stop_id.iloc[i]: q for i, q in r0["stop_use"].items()}
    today = served(prob.base)
    for tag in ["keep", "full_warm", "full_peak-3_warm"]:
        pr = prob if tag != "keep" else O.Problem("keep")
        sr = json.load(open(f"data/opt_{tag}_seasonal.json"))["winter"]
        net = pr.network({k: {q: (h if h is not None else math.inf) for q, h in v.items()} for k, v in sr.items()})
        now = served(net)
        passed = {}
        for p in net:
            if math.isfinite(p.headway.get("09-12", math.inf)):
                for x in p.skip:
                    passed.setdefault(x, []).append(p.name)
        rows = []
        cand = set(passed) | (set(today) - set(now))
        for x in cand:
            if x not in st.index:
                continue
            kind = "dropped" if x not in now else "passed"
            others = [s for s in now if s != x and s in st.index]
            d = walk_min(st.loc[others].stop_lat.values, st.loc[others].stop_lon.values, st.loc[x].stop_lat, st.loc[x].stop_lon) \
                * (P.WALK_KMH * 1000 / 60) / P.DETOUR
            j = int(d.argmin())
            rows.append(dict(stop_id=x, name=st.loc[x].stop_name, kind=kind, lines_today=" ".join(today.get(x, [])),
                             still_served_by=" ".join(now.get(x, [])), passed_by=" ".join(passed.get(x, [])),
                             use_today=round(use.get(x, 0.0)), nearest_served=st.loc[others[j]].stop_name, nearest_m=round(float(d[j]))))
        t = pd.DataFrame(rows).sort_values(["kind", "use_today"], ascending=[True, False])
        t.to_csv(f"data/stops_{tag}.csv", index=False)
        dropped = t[t.kind == "dropped"]; only_passed = t[(t.kind == "passed") & (t.still_served_by == "")]
        print(f"{tag}: dropped {len(dropped)} stops (today's model use {dropped.use_today.sum():,.0f}/day, nearest served stop median "
              f"{dropped.nearest_m.median():.0f} m, max {dropped.nearest_m.max():.0f} m); passed by some line {len(t) - len(dropped)}, "
              f"of which no line stops: {len(only_passed)}")
        print("   busiest dropped:", dropped.head(5)[["name", "use_today", "nearest_served", "nearest_m"]].values.tolist())


if __name__ == "__main__":
    main()
