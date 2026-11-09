"""Hotel shift change at 23:00: does the 23:00 evening end strand hotel workers, and what do trips for them cost?

Today's timetable runs lines 1 and 2 past the North Beach hotels at 23:21-23:28 and 23:51-23:58, which matches
an evening shift ending at 23:00 (shift times are an assumption: 07-15-23 is the common pattern; Eilat job
postings also show 06-14-22, and some hotels run their own staff shuttles). Ending all lines at 23:00 would
remove those trips.

Here each option, with the evening ending at 23:00, gets the same level of SHIFT trips as today: the N_LINES
patterns (of different lines) that, after their first hotel stop, stop at the most stops inside residential
areas (a worker's way home; today these are loops 1 and 2) each get one departure timed to reach their
first hotel stop at SHIFT_END + EXIT_LAG_MIN (clocking out, changing, walking to the stop) and, as today, a
second one 30 minutes later: 4 trips. Buses, bus-hours and driver duties are
recomputed (scripts/blocking.py, scripts/shifts.py).

Usage: PYTHONPATH=.:scripts python3 scripts/shift_trips.py   Output: data/shift_trips.csv
"""
import pandas as pd

import blocking as BL
import evening as EV
import shifts as SH
from eilat import params as P

SHIFT_END_H = 23
EXIT_LAG_MIN = 15     # assumption: shift end -> at the stop (clock out, change, walk through a large hotel)
PASSES = (0, 30)      # minutes after the first pass, as today's two late passes
OPTIONS = ["keep", "full_warm", "full_peak-3_warm"]
N_LINES = 2


def hotel_stops():
    s = pd.read_csv("data/stops_all.csv").set_index("stop_id")
    near = (abs(s.stop_lat - 29.5535) < 0.004) & (abs(s.stop_lon - 34.9625) < 0.006)
    return set(s.index[near | s.stop_name.str.contains("מלון")])


def home_stops():
    import geopandas as gpd
    a = gpd.read_file("data/areas.geojson")
    res = a[a.use == "מגורים"].geometry.union_all()
    s = pd.read_csv("data/stops_all.csv")
    pts = gpd.GeoSeries(gpd.points_from_xy(s.stop_lon, s.stop_lat), crs=a.crs)
    return set(s.stop_id[pts.within(res).values])


HOME = None


def shift_trips(net, hotels):
    global HOME
    HOME = HOME or home_stops()
    rows, cand = [], []
    for p in net:
        if p.line in BL.SCHOOL:
            continue
        idx = [i for i, s in enumerate(p.stops) if s in hotels and s not in p.skip]
        if idx and idx[0] < len(p.stops) - 1:
            after = sum(1 for s in p.stops[idx[0] + 1:] if s in HOME and s not in p.skip)
            cand.append((after, p, idx))
    chosen, lines = [], set()
    for _, p, idx in sorted(cand, key=lambda c: -c[0]):
        if p.line.rstrip("xs") not in lines:
            chosen.append((p, idx)); lines.add(p.line.rstrip("xs"))
        if len(chosen) == N_LINES:
            break
    for p, idx in chosen:
        cum = [0.0]
        for x in p.times("19-24"):
            cum.append(cum[-1] + x)
        for extra in PASSES:
            start = SHIFT_END_H * 60 + EXIT_LAG_MIN + extra - cum[idx[0]]
            rows.append(dict(line=p.line, start=start, end=start + cum[-1], o=p.stops[0], d=p.stops[-1]))
    return pd.DataFrame(rows)


def ops(trips_by_season, st):
    rows = []
    for se, trips in trips_by_season.items():
        B, _, blocks = BL.block(trips, st)
        for sc, dmax in SH.SCENARIOS.items():
            r = SH.staff([p for b in blocks for p in SH.pieces(b, dmax)])
            rows.append(dict(season=se, scenario=sc, buses=len(blocks), bus_hours=B.hours_out.sum(), **r))
    return EV.yearly(pd.DataFrame(rows))


def main():
    st = pd.read_csv("data/stops_all.csv").set_index("stop_id")
    hotels = hotel_stops()
    base = ops({se: BL.option_trips("today", se, st)[lambda t, se=se: ~t.line.isin(BL.SCHOOL) if se == "summer" else t.line.notna()]
                for se in P.SEASONS}, st)
    out = []
    for tag in OPTIONS:
        cut, plus = {}, {}
        n = 0
        for se in P.SEASONS:
            t = BL.option_trips(tag, se, st, 23)
            x = shift_trips(BL.option_net(tag, se), hotels)
            x = x[x.o.isin(st.index) & x.d.isin(st.index)]
            n = len(x)
            if se == "winter":
                print(tag, "shift trips on", sorted(set(x.line)), flush=True)
            cut[se], plus[se] = t, pd.concat([t, x], ignore_index=True)
        for name, tb in (("23:00", cut), ("23:00 + hotel shift trips", plus)):
            y = ops(tb, st)
            row = dict(option=tag, variant=name, shift_trips=n if "+" in name else 0)
            for sc in SH.SCENARIOS:
                row[f"extra_drivers_{sc}"] = y[sc]["headcount"] - base[sc]["headcount"]
            row["buses"] = y["standard"]["buses"]
            row["operating_cost_mnis"] = round((y["standard"]["bus_hours"] - base["standard"]["bus_hours"]) * P.COST_PER_SERVICE_HOUR / 1e6, 2)
            out.append(row); print(row, flush=True)
    pd.DataFrame(out).to_csv("data/shift_trips.csv", index=False)


if __name__ == "__main__":
    main()
