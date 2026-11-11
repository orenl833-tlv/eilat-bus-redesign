"""Desk check before the field check, for the recommended network (data/net_F2.json): what to look at on site.

1. Stops: every stop served today (09:00-12:00, not school lines) that net_F2 drops, or that its lines pass
   without stopping with no other line stopping there. For each: today's lines and departures a day, the model's
   boardings + alightings (calibration A, a weekday), the share of residents 65+ in its area (CBS), and the nearest
   stop still served with the walking distance (straight line x DETOUR). Flagged for a visit: > 300 m walk, or an
   area with >= 15% residents 65+, or a stop with real use (>= 30 a day).
2. Terminals: each end of each line that is new or changed in net_F2 (not one of today's routes). Is it a stop
   where some trip starts or ends today (an existing terminal)? If not, the nearest existing terminal and how far.
   A line's two directions must also join up at each end along streets buses drive today (the stop graph).

Usage: PYTHONPATH=.:scripts python3 analysis/field_check.py   Output: data/field_check_stops.csv,
data/field_check_terminals.csv, printed summary
"""
import math

import geopandas as gpd
import pandas as pd

import blocking as BL
import optimize as O
from eilat import params as P
from eilat.evaluate import walk_min
from stop_table import served

NET = "net_F2"


def main():
    prob = O.Problem("design")
    st = prob.sg.stops.drop_duplicates("stop_id").set_index("stop_id")
    r0 = prob.m.run(prob.base, "winter", K=prob.cal["K"], track=True, **prob.kw)
    use = {prob.m.ev.stops.stop_id.iloc[i]: q for i, q in r0["stop_use"].items()}
    base = [p for p in prob.base if p.line not in O.SCHOOL]
    net = [p for p in BL.option_net(NET, "winter") if p.line not in O.SCHOOL]
    today, now = served(base), served(net)
    passed = {}
    for p in net:
        if math.isfinite(p.headway.get("09-12", math.inf)):
            for x in p.skip:
                passed.setdefault(x, []).append(p.line)
    g = pd.read_csv("data/gtfs_eilat/stop_times.csv")
    dep_today = g.groupby("stop_id").trip_id.nunique()
    areas = gpd.read_file("data/areas.geojson")[["stat11", "age65_pcnt", "geometry"]]
    rows = []
    for x in sorted((set(today) - set(now)) | {s for s in passed if s not in now}):
        if x not in st.index:
            continue
        others = [s for s in now if s in st.index]
        d = walk_min(st.loc[others].stop_lat.values, st.loc[others].stop_lon.values, st.loc[x].stop_lat, st.loc[x].stop_lon) \
            * (P.WALK_KMH * 1000 / 60)
        j = int(d.argmin())
        rows.append(dict(stop_id=x, name=st.loc[x].stop_name, kind="dropped" if x not in passed else "passed",
                         lines_today=" ".join(sorted(set(today.get(x, [])))), departures_today=int(dep_today.get(x, 0)),
                         use_today=round(use.get(x, 0.0)), nearest_served=st.loc[others[j]].stop_name,
                         walk_m=round(float(d[j])), lat=st.loc[x].stop_lat, lon=st.loc[x].stop_lon))
    S = pd.DataFrame(rows)
    pts = gpd.GeoDataFrame(S, geometry=gpd.points_from_xy(S.lon, S.lat), crs=areas.crs)
    S = gpd.sjoin(pts, areas, how="left", predicate="within").drop(columns=["geometry", "index_right"])
    S["visit"] = (S.walk_m > 300) | (S.age65_pcnt >= 15) | (S.use_today >= 30)
    S = S.sort_values(["visit", "use_today"], ascending=[False, False])
    S.drop(columns=["lat", "lon"]).to_csv("data/field_check_stops.csv", index=False)
    print(f"stops losing service: {len(S)} ({(S.kind == 'dropped').sum()} dropped, {(S.kind == 'passed').sum()} passed); "
          f"model use {S.use_today.sum():,.0f}/day; walk to the nearest served stop median {S.walk_m.median():.0f} m, max {S.walk_m.max():.0f} m")
    print(f"to visit: {int(S.visit.sum())} (over 300 m: {(S.walk_m > 300).sum()}, areas with 65+ >= 15%: {(S.age65_pcnt >= 15).sum()}, "
          f"use >= 30/day: {(S.use_today >= 30).sum()})")
    print(S[S.visit].head(12)[["name", "kind", "lines_today", "departures_today", "use_today", "age65_pcnt", "nearest_served", "walk_m"]].to_string(index=False))
    # terminals of new or changed lines
    gs = g.sort_values("stop_sequence").groupby("trip_id").stop_id
    first, last = gs.first(), gs.last()
    terms = set(first) | set(last)
    base_routes = {tuple(p.stops) for p in base}
    trow = []
    for p in net:
        if tuple(p.stops) in base_routes:
            continue
        for end, s in (("start", p.stops[0]), ("end", p.stops[-1])):
            if s in terms:
                near, m = st.loc[s].stop_name, 0
            else:
                tt = [t for t in terms if t in st.index]
                d = walk_min(st.loc[tt].stop_lat.values, st.loc[tt].stop_lon.values, st.loc[s].stop_lat, st.loc[s].stop_lon) * (P.WALK_KMH * 1000 / 60)
                k = int(d.argmin()); near, m = st.loc[tt[k]].stop_name, round(float(d[k]))
            trow.append(dict(line=p.line, pattern=p.name, end=end, stop_id=s, stop=st.loc[s].stop_name,
                             existing_terminal=s in terms, nearest_terminal=near, terminal_m=m))
    T = pd.DataFrame(trow)
    # can the two directions turn round at each end? (the other direction starts near where this one ends)
    T.to_csv("data/field_check_terminals.csv", index=False)
    print("\nends of new or changed lines:")
    print(T.to_string(index=False))


if __name__ == "__main__":
    main()
