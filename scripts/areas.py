"""Eilat statistical areas: boundaries, population and car ownership, on one map.

Boundaries: CBS layer of 2011 statistical areas with 2020 population (the newest published polygons).
Census 2022 attributes (households without a car, etc.) use a newer division of a few areas, so they are
attached to the 2011 polygons:
- codes that exist in both (14, 15, 16, 21, 22, 24, 25, 31, 32) map one to one;
- 2011 area 23 was split into 2022 areas 23 and 26;
- 2011 areas 33-36 (the newer northern neighbourhoods) were re-divided into 2022 areas 42-47, so they
  get the population-weighted average of 42-47 as one group.
CBS also merges small areas for publication ("Stat11_Unite"), e.g. 12+11, 14+13, 15+16.

Outputs: data/areas.geojson (WGS84), data/areas.csv, figs/areas.png
"""
import os

import geopandas as gpd
import matplotlib
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

GDB = "data/raw/cbs_sa/statisticalareas_2020_demography.gdb"
MAP_2022 = {14: [14], 15: [15], 16: [16], 21: [21], 22: [22], 24: [24], 25: [25], 31: [31], 32: [32],
            23: [23, 26], 33: [42, 43, 44, 45, 46, 47], 34: [42, 43, 44, 45, 46, 47],
            35: [42, 43, 44, 45, 46, 47], 36: [42, 43, 44, 45, 46, 47]}
INK, INK2, SURF = "#0b0b0b", "#52514e", "#fcfcfb"


def census_for(c, codes):
    p = c[c.StatArea.isin(codes)]
    w = p.pop_approx
    out = {"pop2022_group": int(w.sum())}
    for col in ["Vehicle0_pcnt", "age0_19_pcnt", "age65_pcnt", "Empl_pcnt"]:
        out[col] = round(float((pd.to_numeric(p[col], errors="coerce") * w).sum() / w.sum()), 1)
    out["codes2022"] = "+".join(str(int(x)) for x in codes)
    return out


def main():
    g = gpd.read_file(GDB)
    g = g[g.SEMEL_YISHUV == 2600].copy()
    g["stat11"] = g.STAT11.astype(int)
    c = pd.read_csv("data/census2022_eilat.csv")
    c = c[c.StatArea.notna()].assign(StatArea=lambda x: x.StatArea.astype(int))
    rows = [dict(stat11=s, **census_for(c, codes)) for s, codes in MAP_2022.items()]
    g = g.merge(pd.DataFrame(rows), on="stat11", how="left")
    g["pop2020"] = g.Pop_Total
    g["area_km2"] = g.geometry.area / 1e6
    g["use"] = g.Main_Function_Txt
    g = g.to_crs(4326)
    cen = g.geometry.representative_point()
    g["lat"], g["lon"] = cen.y.round(5), cen.x.round(5)
    keep = ["stat11", "Stat11_Unite", "use", "pop2020", "area_km2", "codes2022", "pop2022_group", "Vehicle0_pcnt",
            "age0_19_pcnt", "age65_pcnt", "lat", "lon"]
    g[keep + ["geometry"]].to_file("data/areas.geojson", driver="GeoJSON")
    g[keep].round(3).to_csv("data/areas.csv", index=False)
    print(g[keep].round(2).to_string(index=False))
    print("population 2020 in layer:", int(g.pop2020.sum()), "| census 2022:", int(c.pop_approx.sum()))

    os.makedirs("figs", exist_ok=True)
    fig, axes = plt.subplots(1, 2, figsize=(12, 7.5), dpi=150, facecolor=SURF)
    for ax, col, title, cmap in [(axes[0], "pop2020", "Residents (2020)", "Blues"),
                                 (axes[1], "Vehicle0_pcnt", "Households without a car (census 2022, %)", "Oranges")]:
        g.plot(column=col, ax=ax, cmap=cmap, edgecolor="#ffffff", lw=.8, legend=True,
               legend_kwds=dict(shrink=.6), missing_kwds=dict(color="#e4e3df"))
        for _, r in g.iterrows():
            ax.annotate(str(r.stat11), (r.lon, r.lat), ha="center", va="center", fontsize=8, color=INK, fontweight="bold")
        ax.set_title(title, loc="left", fontsize=11, color=INK); ax.set_axis_off()
        ax.set_xlim(34.895, 34.985); ax.set_ylim(29.495, 29.59)
    sch = pd.read_csv("data/mosdot_now_eilat.csv")
    sch = sch[sch.TEUR_TAT_SUG_MISGERET == "בית ספר"]
    pts = gpd.GeoDataFrame(sch, geometry=gpd.points_from_xy(sch.X, sch.Y), crs=2039).to_crs(4326)
    for ax in axes:
        pts.plot(ax=ax, color=INK, markersize=10, marker="^")
        ax.scatter([34.9612], [29.5742], s=60, color="#2a78d6", marker="s", zorder=5)
    axes[0].text(34.9612, 29.5742, "  depot", fontsize=8, color=INK, va="center")
    fig.text(.02, .02, "Grey: no residents (public or open land). Triangles: schools (active 2026). "
             "Source: CBS statistical areas 2011 / population 2020, census 2022; Education Ministry.",
             fontsize=8, color=INK2)
    fig.tight_layout(rect=(0, .03, 1, 1)); fig.savefig("figs/areas.png")


if __name__ == "__main__":
    main()
