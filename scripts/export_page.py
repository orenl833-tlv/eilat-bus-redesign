"""Data for the interactive comparison page (web/eilat.html): one JSON with stops, area outlines, and for each
network x season x period the buses an hour on every street segment; plus per-area perceived-time change and
travel times to key places, and the summary of each option.

Usage: PYTHONPATH=.:scripts python3 scripts/export_page.py   Output: web/data.json
"""
import json
import math
import os

import geopandas as gpd

import pandas as pd

import optimize as O
from eilat import params as P

OPTS = {"today": "Today", "keep": "1 · Keep every line", "full_warm": "2 · Restructure", "full_peak-3_warm": "3 · Restructure, 3 fewer buses"}


def nets(prob, tag):
    if tag == "today":
        return {s: prob.base for s in P.SEASONS}
    sr = json.load(open(f"data/opt_{tag}_seasonal.json"))
    return {s: prob.network({k: {q: (h if h is not None else math.inf) for q, h in v.items()} for k, v in sr[s].items()})
            for s in P.SEASONS}


def segments(net, period, sid):
    seg = {}
    for p in net:
        h = p.headway.get(period, math.inf)
        if not math.isfinite(h):
            continue
        idx = [sid[s] for s in p.stops if s in sid]
        for a, b in zip(idx[:-1], idx[1:], strict=True):
            k = (min(a, b), max(a, b))
            seg[k] = seg.get(k, 0) + 60 / h
    return [[a, b, round(v, 1)] for (a, b), v in seg.items()]


def main():
    os.makedirs("web", exist_ok=True)
    prob_full = O.Problem("full"); prob_keep = O.Problem("keep")
    stops = prob_full.sg.stops.reset_index(drop=True)
    sid = {s: i for i, s in enumerate(stops.stop_id)}
    out = {"stops": [[round(r.stop_lat, 5), round(r.stop_lon, 5), r.stop_name] for r in stops.itertuples()],
           "periods": list(P.PERIODS), "seasons": list(P.SEASONS), "options": OPTS, "net": {}, "areas": [], "summary": {}}
    a = gpd.read_file("data/areas.geojson")
    a = a[a.use == "מגורים"].copy()
    a["geometry"] = a.geometry.simplify(0.0001)
    for r in a.itertuples():
        geom = r.geometry.geoms if r.geometry.geom_type == "MultiPolygon" else [r.geometry]
        rings = [[[round(x, 5), round(y, 5)] for x, y in g.exterior.coords] for g in geom]
        out["areas"].append(dict(id=int(r.stat11), rings=rings, pop=None if pd.isna(r.pop2020) else int(r.pop2020),
                                 nocar=None if pd.isna(r.Vehicle0_pcnt) else float(r.Vehicle0_pcnt)))
    for tag in OPTS:
        prob = prob_keep if tag == "keep" else prob_full
        ns = nets(prob, tag)
        out["net"][tag] = {s: {q: segments(ns[s], q, sid) for q in P.PERIODS} for s in P.SEASONS}
        if tag != "today":
            A = pd.read_csv(f"data/assess_{tag}_areas.csv", index_col=0)
            T = pd.read_csv(f"data/assess_{tag}_traveltime.csv", header=[0, 1], index_col=0)
            S = json.load(open(f"data/assess_{tag}.json"))
            out["summary"][tag] = dict(
                year_A=S["year_A"], year_B=S["year_B"], worst_area=S["worst_area"],
                peak={s: v["peak"] for s, v in S["fleet"].items()}, hours={s: v["hours"] for s, v in S["fleet"].items()},
                area={str(int(i)): round(float((r["worst"] + r["best"]) / 2 - 1) * 100, 1) for i, r in A.iterrows()},
                tt={str(int(i)): {k: [round(float(T.loc[i, ("today", k)]), 1), round(float(T.loc[i, ("proposal", k)]), 1)]
                                  for k in T.columns.get_level_values(1).unique()} for i in T.index})
    out["summary"]["today"] = dict(peak=json.load(open("data/assess_full_warm.json"))["fleet_today"]["peak"],
                                   hours=json.load(open("data/assess_full_warm.json"))["fleet_today"]["hours"])
    json.dump(out, open("web/data.json", "w"), ensure_ascii=False, separators=(",", ":"))
    print("web/data.json", round(os.path.getsize("web/data.json") / 1e3), "kB")



if __name__ == "__main__":
    main()
