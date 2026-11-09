"""Street graph for new routes, built from where buses already drive in Eilat.

Every consecutive pair of stops on any bus trip (urban, airport, intercity) inside the city becomes an
edge, with the median planned running time. New candidate lines are paths in this graph, so they only use
streets that buses already use and existing stops (agreed: no new stops).

Output: data/stop_graph.csv (u, v, minutes, metres, n_trips), data/stops_all.csv
"""
import numpy as np
import pandas as pd

SRC = "data/raw/gtfs_20261107"
BOX = dict(lat=(29.48, 29.60), lon=(34.88, 35.00))


def secs(t):
    h, m, s = (int(x) for x in t.split(":"))
    return h * 3600 + m * 60 + s


def main():
    stops = pd.read_csv(f"{SRC}/stops.txt", encoding="utf-8-sig")
    stops = stops[stops.stop_lat.between(*BOX["lat"]) & stops.stop_lon.between(*BOX["lon"])]
    ids = set(stops.stop_id)
    parts = []
    for ch in pd.read_csv(f"{SRC}/stop_times.txt", encoding="utf-8-sig", chunksize=3_000_000,
                          usecols=["trip_id", "arrival_time", "departure_time", "stop_id", "stop_sequence",
                                   "shape_dist_traveled"]):
        parts.append(ch[ch.stop_id.isin(ids)])
    st = pd.concat(parts).sort_values(["trip_id", "stop_sequence"])
    st["arr"] = st.arrival_time.map(secs); st["dep"] = st.departure_time.map(secs)
    nx = st.groupby("trip_id").shift(-1)
    e = pd.DataFrame({"u": st.stop_id, "v": nx.stop_id, "sec": nx.arr - st.dep,
                      "m": nx.shape_dist_traveled - st.shape_dist_traveled,
                      "seq_gap": nx.stop_sequence - st.stop_sequence}).dropna()
    e = e[(e.seq_gap == 1) & (e.sec >= 0) & (e.m > 0)]
    e = e.astype({"u": int, "v": int})
    g = e.groupby(["u", "v"]).agg(minutes=("sec", lambda s: s.median() / 60), metres=("m", "median"),
                                  n_trips=("sec", "size")).reset_index()
    # a zero planned time between stops (same minute) gets a floor from distance at 25 km/h
    g["minutes"] = np.maximum(g.minutes, g.metres / (25_000 / 60))
    g.to_csv("data/stop_graph.csv", index=False)
    used = set(g.u) | set(g.v)
    stops[stops.stop_id.isin(used)][["stop_id", "stop_code", "stop_name", "stop_lat", "stop_lon"]].to_csv(
        "data/stops_all.csv", index=False)
    print(f"{len(g)} directed stop-to-stop edges between {len(used)} stops")


if __name__ == "__main__":
    main()
