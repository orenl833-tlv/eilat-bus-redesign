"""Map of today's urban bus network: every route shape, coloured and sized by trips a day on it.

Segments shared by several lines add up, so the map shows service on each street, not per line.
Input: data/gtfs_eilat (gtfs_eilat.py), data/areas.geojson. Output: figs/network.png, data/line_stats.csv
"""
import geopandas as gpd
import matplotlib
import numpy as np
import pandas as pd
from matplotlib.collections import LineCollection

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

G = "data/gtfs_eilat"


def main():
    tr = pd.read_csv(f"{G}/trips.csv"); r = pd.read_csv(f"{G}/routes.csv"); sh = pd.read_csv(f"{G}/shapes.csv")
    st = pd.read_csv(f"{G}/stop_times.csv")
    tr = tr.merge(r[["route_id", "route_short_name"]], on="route_id")
    # per line: trips, length, first/last departure, run time
    span = st.groupby("trip_id").agg(t0=("dep", "min"), t1=("arr", "max"), km=("shape_dist_traveled", "max"))
    x = tr.join(span, on="trip_id")
    ls = x.groupby("route_short_name").agg(trips=("trip_id", "size"), first=("t0", "min"), last=("t0", "max"),
                                           run_min=("t1", lambda s: 0), km=("km", "median"))
    ls["run_min"] = (x.t1 - x.t0).groupby(x.route_short_name).median() / 60
    ls["km"] = ls.km / 1000
    ls["first"] = (ls["first"] // 3600).astype(int).astype(str).str.zfill(2) + ":" + ((ls["first"] % 3600) // 60).astype(int).astype(str).str.zfill(2)
    ls["last"] = (ls["last"] // 3600).astype(int).astype(str).str.zfill(2) + ":" + ((ls["last"] % 3600) // 60).astype(int).astype(str).str.zfill(2)
    ls.round(1).to_csv("data/line_stats.csv")
    print(ls.round(1).sort_values("trips", ascending=False).to_string())

    # trips per 50 m street cell, summed over all shapes, weighted by trips on each shape
    n = tr.groupby("shape_id").size()
    sh = sh.sort_values(["shape_id", "shape_pt_sequence"])
    segs, w = [], []
    for sid, g in sh.groupby("shape_id"):
        xy = g[["shape_pt_lon", "shape_pt_lat"]].values
        segs += list(zip(xy[:-1], xy[1:], strict=True)); w += [n.get(sid, 0)] * (len(xy) - 1)
    seg = pd.DataFrame({"a": [tuple(np.round(a, 4)) for a, _ in segs], "b": [tuple(np.round(b, 4)) for _, b in segs], "w": w})
    seg["key"] = [tuple(sorted((a, b))) for a, b in zip(seg.a, seg.b, strict=True)]
    agg = seg.groupby("key").w.sum()
    lines = [list(k) for k in agg.index]
    vals = agg.values

    areas = gpd.read_file("data/areas.geojson")
    fig, ax = plt.subplots(figsize=(8, 9.5), dpi=150, facecolor="#fcfcfb")
    areas.plot(ax=ax, color="#efeeea", edgecolor="#ffffff", lw=.8)
    res = areas[areas.use == "מגורים"]
    res.plot(ax=ax, column="Vehicle0_pcnt", cmap="Oranges", alpha=.45, edgecolor="#ffffff", lw=.8)
    order = np.argsort(vals)
    cmap = matplotlib.colormaps["Blues"]
    lc = LineCollection([lines[i] for i in order], colors=[cmap(.35 + .65 * min(vals[i], 150) / 150) for i in order],
                        linewidths=[.6 + 3.4 * min(vals[i], 150) / 150 for i in order], capstyle="round")
    ax.add_collection(lc)
    ax.scatter([34.9612], [29.5742], s=50, color="#0b0b0b", marker="s", zorder=5)
    ax.annotate("depot", (34.9612, 29.5742), xytext=(6, 0), textcoords="offset points", fontsize=8, va="center")
    ax.set_xlim(34.895, 34.985); ax.set_ylim(29.49, 29.59); ax.set_axis_off()
    ax.set_aspect(1 / np.cos(np.radians(29.55)))
    ax.set_title("Eilat urban buses today: trips a day on each street (darker and thicker = more)\n"
                 "Orange under it: share of households without a car", loc="left", fontsize=10)
    sm = plt.cm.ScalarMappable(cmap=matplotlib.colors.LinearSegmentedColormap.from_list(
        "b", [cmap(.35), cmap(1.0)]), norm=matplotlib.colors.Normalize(0, 150))
    fig.colorbar(sm, ax=ax, shrink=.4, label="bus trips a day (both directions, capped at 150)")
    fig.text(.02, .01, "Timetable: GTFS, Tuesday 10 Nov 2026. Areas: CBS. ", fontsize=7, color="#52514e")
    fig.tight_layout(); fig.savefig("figs/network.png")


if __name__ == "__main__":
    main()
