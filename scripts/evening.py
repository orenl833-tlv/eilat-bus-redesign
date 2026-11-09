"""Ending the evening earlier: how many drivers it saves and what it costs passengers.

The options run most lines to midnight. That makes many bus days longer than two driver shifts, and so needs
10-17 more drivers (scripts/shifts.py) in a national driver shortage. Here each option is re-timed with the
last departures earlier, and checked for:
- perceived door-to-door time vs today (scripts/assess.py's evaluation, calibrations A and B, by season);
- the worst-off area;
- buses, bus-hours and driver duties (scripts/blocking.py, scripts/shifts.py), and their yearly cost.

How a shorter evening enters the evaluation: the model has one evening period, 19-24, and represents it by
its average headway, exactly as it represents today's network (whose evening thins out after 21:00). Ending
at 23:00 leaves 4 of the 5 hours, so the average headway grows x 5/4; at 22:00, x 5/3. This treats a late
trip that is cut the same way the model already treats today's thin late evening.

Usage: PYTHONPATH=.:scripts python3 scripts/evening.py   Output: data/evening.csv
"""
import math

import pandas as pd

import assess as AS
import blocking as BL
import shifts as SH
from eilat import params as P

OPTIONS = ["keep", "full_warm", "full_peak-3_warm"]
QUIET = ("winter", "spring_autumn")
VARIANTS = {   # name: season -> last departure hour (None = as proposed, to midnight)
    "as proposed": {},
    "23:00 in winter and spring/autumn": {s: 23 for s in QUIET},
    "23:00 all year": {s: 23 for s in P.SEASONS},
    "22:00 in winter and spring/autumn": {s: 22 for s in QUIET},
}
W = {s: v["months"] / 12 for s, v in P.SEASONS.items()}
DAYS = {s: W[s] * P.WEEKDAYS_PER_YEAR for s in P.SEASONS}


def thinned(net, last):
    """The network as the evaluation sees it when the evening ends at `last`."""
    if not last:
        return net
    out = []
    for p in net:
        h = p.headway.get("19-24", math.inf)
        if math.isfinite(h):
            q = type(p)(**{**p.__dict__, "headway": {**p.headway, "19-24": h * 5 / (last - 19)}})
            out.append(q)
        else:
            out.append(p)
    return out


def operations(tag, cut, st):
    """Per season: buses, bus-hours and driver duties under both duty scenarios."""
    rows = []
    for se in P.SEASONS:
        trips = BL.option_trips(tag, se, st, cut.get(se))
        if tag == "today" and se == "summer":
            trips = trips[~trips.line.isin(BL.SCHOOL)]
        B, peak, blocks = BL.block(trips, st)
        for sc, dmax in SH.SCENARIOS.items():
            r = SH.staff([p for b in blocks for p in SH.pieces(b, dmax)])
            rows.append(dict(season=se, scenario=sc, buses=len(blocks), bus_hours=B.hours_out.sum(), **r))
    return pd.DataFrame(rows)


def yearly(ops):
    """Headcount (busiest season x roster factor), paid driver hours and bus-hours a year, per scenario."""
    out = {}
    for sc, g in ops.groupby("scenario"):
        d = g.season.map(DAYS)
        out[sc] = dict(headcount=round(g.duties.max() * SH.ROSTER_FACTOR), driver_cost=(g.cost_day * d).sum(),
                       bus_hours=(g.bus_hours * d).sum(), buses=g.buses.max())
    return out


def main():
    st = pd.read_csv("data/stops_all.csv").set_index("stop_id")
    base = yearly(operations("today", {}, st))
    rows = []
    for tag in OPTIONS:
        prob = BL.option_net.__globals__["O"].Problem("keep" if tag == "keep" else "full", -3 if "peak-3" in tag else 0)
        for name, cut in VARIANTS.items():
            nets = {se: thinned(BL.option_net(tag, se), cut.get(se)) for se in P.SEASONS}
            res = AS.eval_net(prob, nets)
            year = {v: sum(W[s] * res[(s, v)]["cost"] for s in P.SEASONS) for v in ("A", "B")}
            worst = max(float(res[(s, v)]["area"].max()) for s in P.SEASONS for v in ("A", "B"))
            y = yearly(operations(tag, cut, st))
            row = dict(option=tag, variant=name, perceived_A=round(year["A"], 4), perceived_B=round(year["B"], 4),
                       worst_area=round(worst, 3))
            for sc in SH.SCENARIOS:
                row[f"extra_drivers_{sc}"] = y[sc]["headcount"] - base[sc]["headcount"]
                row[f"driver_cost_mnis_{sc}"] = round((y[sc]["driver_cost"] - base[sc]["driver_cost"]) / 1e6, 2)
            row["buses"] = y["standard"]["buses"]
            row["bus_hours_pct"] = round((y["standard"]["bus_hours"] / base["standard"]["bus_hours"] - 1) * 100, 1)
            # the operator's whole cost moves with bus-hours (NIS 360 each, drivers included)
            row["operating_cost_mnis"] = round((y["standard"]["bus_hours"] - base["standard"]["bus_hours"]) * P.COST_PER_SERVICE_HOUR / 1e6, 2)
            rows.append(row)
            print(row, flush=True)
    R = pd.DataFrame(rows)
    R.to_csv("data/evening.csv", index=False)
    print(f"today: {base}")


if __name__ == "__main__":
    main()
