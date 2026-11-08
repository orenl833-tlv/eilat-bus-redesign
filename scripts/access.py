"""Baseline accessibility: door-to-door travel time by bus (walk + wait + ride + transfers) from every
residential area of Eilat to each attractor, by time of day, on today's timetable.

Method: Connection Scan Algorithm on the GTFS of one weekday (gtfs_eilat.py), vectorised over origin
points. From an origin point you may walk to any stop within WALK_MAX metres; between stops you may walk
up to TRANSFER_MAX metres; from the last stop you walk to the attractor. Walking is always an option.
Distances are straight lines × DETOUR, at WALK_KMH. Departure times every 10 minutes in each window;
the result is the median over departures, so waiting time is included as a passenger who doesn't time
the timetable would face.

Origins: OPTS random points inside each residential statistical area (areas.geojson), fixed seed.
Outputs: data/access_tt.csv (one row per origin point × departure × attractor), data/access_summary.csv,
figs/access.png.
"""
import os

import geopandas as gpd
import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

G = "data/gtfs_eilat"
WALK_KMH, DETOUR = 4.5, 1.3
WALK_MAX, TRANSFER_MAX = 800, 300
OPTS = 12
WINDOWS = {"07:00": 7 * 3600, "10:00": 10 * 3600, "13:00": 13 * 3600, "17:00": 17 * 3600, "21:00": 21 * 3600}
DEPS = range(0, 3600, 600)
CAP = 120 * 60
ATTRACTORS = {  # name: (lat, lon, category), anchored on GTFS stop locations (see FLEET.md / ATTRACTORS.md)
    "City hall / centre": (29.5561, 34.9520, "centre"),
    "Hotels, North Beach": (29.5535, 34.9625, "hotels"),
    "Ice Mall": (29.5549, 34.9661, "shopping"),
    "Mall HaYam": (29.5511, 34.9550, "shopping"),
    "Big centre": (29.5677, 34.9596, "shopping"),
    "Yoseftal hospital": (29.5549, 34.9401, "health"),
    "Eilat campus": (29.5665, 34.9522, "education"),
    "Rabin high school": (29.5534, 34.9358, "school"),
    "Begin high school": (29.5622, 34.9379, "school"),
    "Goldwater high school": (29.5536, 34.9481, "school"),
    "Coral Beach": (29.5082, 34.9207, "beach"),
    "Taba / Princess": (29.4959, 34.9075, "beach"),
    "City entrance terminal": (29.5713, 34.9623, "terminal"),
    "Port": (29.5355, 34.9404, "work"),
}
MX, MY = 111_320 * np.cos(np.radians(29.55)), 110_850


def walk_s(lat1, lon1, lat2, lon2):
    d = np.hypot((np.asarray(lon1) - lon2) * MX, (np.asarray(lat1) - lat2) * MY) * DETOUR
    return d / (WALK_KMH / 3.6)


def load():
    stops = pd.read_csv(f"{G}/stops.csv").reset_index(drop=True)
    sidx = {s: i for i, s in enumerate(stops.stop_id)}
    st = pd.read_csv(f"{G}/stop_times.csv").sort_values(["trip_id", "stop_sequence"])
    st["s"] = st.stop_id.map(sidx)
    nxt = st.groupby("trip_id").shift(-1)
    c = pd.DataFrame({"trip": st.trip_id, "u": st.s, "dep": st.dep, "v": nxt.s, "arr": nxt.arr}).dropna()
    c = c.astype({"u": int, "v": int, "dep": int, "arr": int})
    c["trip"] = c.trip.astype("category").cat.codes
    c = c.sort_values(["dep", "arr"]).reset_index(drop=True)
    lat, lon = stops.stop_lat.values, stops.stop_lon.values
    w = walk_s(lat[:, None], lon[:, None], lat[None, :], lon[None, :])
    fp = [np.where((w[i] > 0) & (w[i] <= TRANSFER_MAX * DETOUR / (WALK_KMH / 3.6)))[0] for i in range(len(stops))]
    fpt = [w[i, fp[i]] for i in range(len(stops))]
    return stops, c, fp, fpt


def origins():
    a = gpd.read_file("data/areas.geojson")
    a = a[a.use == "מגורים"].copy()
    rows = []
    for r in a.itertuples():
        pts = gpd.GeoSeries([r.geometry], crs=a.crs).sample_points(OPTS, rng=int(r.stat11)).iloc[0]
        for p in pts.geoms:
            rows.append(dict(stat11=r.stat11, lat=p.y, lon=p.x))
    return pd.DataFrame(rows), a


def scan(c, fp, fpt, ea0, t0):
    """Earliest arrival at every stop for many queries at once. ea0: (queries × stops) initial times."""
    ea = ea0.copy()
    ntrip = int(c.trip.max()) + 1
    on = np.zeros((ea.shape[0], ntrip), bool)
    cc = c[(c.dep >= t0) & (c.dep <= t0 + CAP)]
    for trip, u, dep, v, arr in zip(cc.trip.values, cc.u.values, cc.dep.values, cc.v.values, cc.arr.values, strict=True):
        ok = on[:, trip] | (ea[:, u] <= dep)
        if not ok.any():
            continue
        on[:, trip] |= ok
        better = ok & (arr < ea[:, v])
        if better.any():
            ea[better, v] = arr
            for j, wt in zip(fp[v], fpt[v], strict=True):
                ea[better, j] = np.minimum(ea[better, j], arr + wt)
    return ea


def main():
    stops, c, fp, fpt = load()
    o, areas = origins()
    slat, slon = stops.stop_lat.values, stops.stop_lon.values
    acc = walk_s(o.lat.values[:, None], o.lon.values[:, None], slat[None, :], slon[None, :])
    acc[acc > WALK_MAX * DETOUR / (WALK_KMH / 3.6)] = np.inf
    names = list(ATTRACTORS)
    alat = np.array([ATTRACTORS[n][0] for n in names]); alon = np.array([ATTRACTORS[n][1] for n in names])
    egr = walk_s(slat[:, None], slon[:, None], alat[None, :], alon[None, :])
    egr[egr > WALK_MAX * DETOUR / (WALK_KMH / 3.6)] = np.inf
    direct = walk_s(o.lat.values[:, None], o.lon.values[:, None], alat[None, :], alon[None, :])
    out = []
    for wname, w0 in WINDOWS.items():
        for d in DEPS:
            t0 = w0 + d
            ea = scan(c, fp, fpt, t0 + acc, t0)
            arrive = (ea[:, :, None] + egr[None, :, :]).min(axis=1)  # queries × attractors
            tt = np.minimum(arrive - t0, direct)
            tt = np.minimum(tt, CAP)
            df = pd.DataFrame(tt / 60, columns=names)
            df["stat11"], df["pt"], df["window"], df["dep"] = o.stat11.values, np.arange(len(o)), wname, t0
            out.append(df)
        print(wname, "done", flush=True)
    t = pd.concat(out).melt(id_vars=["stat11", "pt", "window", "dep"], var_name="attractor", value_name="tt_min")
    t.round(2).to_csv("data/access_tt.csv", index=False)
    s = t.groupby(["stat11", "attractor", "window"]).tt_min.median().unstack("window").round(1)
    s.to_csv("data/access_summary.csv")
    walk = pd.DataFrame(direct / 60, columns=names).assign(stat11=o.stat11.values).groupby("stat11").median()

    # city view: weight each area by residents without a car (likely riders) and by all residents
    areas = areas.set_index("stat11")
    wt_all = areas.pop2020.fillna(0)
    wt_nocar = (areas.pop2020 * areas.Vehicle0_pcnt / 100).fillna(0)
    rows = []
    for n in names:
        for wname in WINDOWS:
            v = s.xs(n, level="attractor")[wname]
            rows.append(dict(attractor=n, window=wname,
                             tt_all=round(float((v * wt_all).sum() / wt_all[v.index].sum()), 1),
                             tt_nocar=round(float((v * wt_nocar).sum() / wt_nocar[v.index].sum()), 1)))
    city = pd.DataFrame(rows)
    city.to_csv("data/access_city.csv", index=False)
    print(city.pivot(index="attractor", columns="window", values="tt_nocar").to_string())
    print("\nmedian walking time (min) for comparison:")
    print((walk.T * wt_all[walk.index]).sum(axis=1).div(wt_all[walk.index].sum()).round(0).to_string())

    # map: median travel time at 10:00 to four attractors
    os.makedirs("figs", exist_ok=True)
    pick = ["City hall / centre", "Hotels, North Beach", "Coral Beach", "Yoseftal hospital"]
    fig, axes = plt.subplots(1, 4, figsize=(16, 5.6), dpi=140, facecolor="#fcfcfb")
    for ax, n in zip(axes, pick, strict=True):
        v = s.xs(n, level="attractor")["10:00"]
        g = areas.assign(tt=v.reindex(areas.index)).reset_index()
        g.plot(column="tt", ax=ax, cmap="YlOrRd", vmin=5, vmax=60, edgecolor="white", lw=.8,
               missing_kwds=dict(color="#e4e3df"))
        for r in g.itertuples():
            if not np.isnan(r.tt):
                ax.annotate(f"{r.tt:.0f}", (r.lon, r.lat), ha="center", va="center", fontsize=7.5)
        ax.scatter([ATTRACTORS[n][1]], [ATTRACTORS[n][0]], marker="*", s=160, color="#2a78d6", zorder=5)
        ax.set_xlim(34.895, 34.985); ax.set_ylim(29.49, 29.585); ax.set_axis_off()
        ax.set_title(f"to {n}", loc="left", fontsize=10)
    fig.suptitle("Door-to-door minutes by bus at 10:00 (median over departures every 10 min; walking, waiting, "
                 "riding, transfers)", x=.01, ha="left", fontsize=12)
    fig.tight_layout(); fig.savefig("figs/access.png")


if __name__ == "__main__":
    main()
