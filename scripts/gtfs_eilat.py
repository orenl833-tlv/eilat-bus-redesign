"""Cut the national GTFS down to Eilat's urban lines on one service day.

Input: data/raw/gtfs_20261107 (Ministry of Transport GTFS, 7 Nov 2026). Day: Tuesday 10 Nov 2026, a
regular school-term weekday. Urban lines as in fleet.py, operator Egged (agency 3).

Outputs in data/gtfs_eilat/: routes.csv, trips.csv, stop_times.csv (times as seconds after midnight),
stops.csv, shapes.csv.
"""
import os

import pandas as pd

SRC = "data/raw/gtfs_20261107"
OUT = os.environ.get("GTFS_OUT", "data/gtfs_eilat")
DAY = os.environ.get("GTFS_DAY", "20261110")
URBAN = {"1", "1א", "2", "3", "4", "5", "5א", "6", "6א", "10", "11", "15", "16", "80", "80א", "81", "82"}


def secs(t):
    h, m, s = (int(x) for x in t.split(":"))
    return h * 3600 + m * 60 + s


def main():
    os.makedirs(OUT, exist_ok=True)
    rd = lambda f, **k: pd.read_csv(f"{SRC}/{f}", encoding="utf-8-sig", **k)  # noqa: E731
    routes = rd("routes.txt")
    routes = routes[(routes.agency_id == 3) & routes.route_short_name.astype(str).isin(URBAN)
                    & routes.route_long_name.str.contains("אילת")]
    # keep only routes whose both ends are in Eilat (drops same-numbered lines elsewhere run by Egged)
    routes = routes[routes.route_long_name.str.count("אילת") >= 2]
    cal = rd("calendar.txt", dtype={"start_date": str, "end_date": str})
    wd = pd.Timestamp(DAY).day_name().lower()
    active = set(cal[(cal.start_date <= DAY) & (cal.end_date >= DAY) & (cal[wd] == 1)].service_id)
    trips = rd("trips.txt")
    trips = trips[trips.route_id.isin(routes.route_id) & trips.service_id.isin(active)]
    ids = set(trips.trip_id)
    parts = []
    for ch in pd.read_csv(f"{SRC}/stop_times.txt", encoding="utf-8-sig", chunksize=2_000_000,
                          usecols=["trip_id", "arrival_time", "departure_time", "stop_id", "stop_sequence",
                                   "shape_dist_traveled"]):
        parts.append(ch[ch.trip_id.isin(ids)])
    st = pd.concat(parts)
    st["arr"] = st.arrival_time.map(secs); st["dep"] = st.departure_time.map(secs)
    stops = rd("stops.txt")
    stops = stops[stops.stop_id.isin(st.stop_id)]
    sh_ids = set(trips.shape_id.dropna())
    sparts = [ch[ch.shape_id.isin(sh_ids)] for ch in pd.read_csv(f"{SRC}/shapes.txt", encoding="utf-8-sig",
                                                                  chunksize=3_000_000)]
    shapes = pd.concat(sparts)
    routes.to_csv(f"{OUT}/routes.csv", index=False); trips.to_csv(f"{OUT}/trips.csv", index=False)
    st.to_csv(f"{OUT}/stop_times.csv", index=False); stops.to_csv(f"{OUT}/stops.csv", index=False)
    shapes.to_csv(f"{OUT}/shapes.csv", index=False)
    per = trips.merge(routes[["route_id", "route_short_name", "route_long_name"]], on="route_id")
    print(f"{DAY}: {len(routes)} route variants, {len(trips)} trips, {len(st):,} stop times, {len(stops)} stops")
    print(per.groupby("route_short_name").size().to_string())


if __name__ == "__main__":
    main()
