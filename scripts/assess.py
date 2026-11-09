"""Assess a proposed network against today's: per season and calibration, per area, per line, fleet, maps, and
sensitivity of the result to every assumed number.

Usage: PYTHONPATH=.:scripts python3 scripts/assess.py <tag>
Outputs: data/assess_<tag>.json, data/assess_<tag>_lines.csv, data/assess_<tag>_areas.csv, figs/proposal_<tag>.png
"""
import json
import math
import os
import sys

import geopandas as gpd
import matplotlib
import numpy as np
import pandas as pd
from matplotlib.collections import LineCollection

import optimize as O
from eilat import demand as D
from eilat import network as N
from eilat import params as P

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

KEY = ["City hall / centre", "Hotels, North Beach", "Big centre", "Yoseftal hospital", "Coral Beach",
       "Old central station (Star Eilat)"]


def load(tag):
    s = O.load_state(f"data/opt_{tag}.json") if hasattr(O, "load_state") else None
    raw = json.load(open(f"data/opt_{tag}.json"))
    base = {k: {q: (h if h is not None else math.inf) for q, h in v.items()} for k, v in raw.items()}
    seas = None
    if os.path.exists(f"data/opt_{tag}_seasonal.json"):
        sr = json.load(open(f"data/opt_{tag}_seasonal.json"))
        seas = {se: {k: {q: (h if h is not None else math.inf) for q, h in v.items()} for k, v in st.items()}
                for se, st in sr.items()}
    return base, seas, s


def eval_net(prob, nets, **over):
    """nets: season -> pattern list. Returns cost ratios vs today per (season, calibration), per area."""
    out = {}
    for s in P.SEASONS:
        kw = dict(prob.kw); kw.update({k: v for k, v in over.items() if k in ("lam", "const", "car_prop")})
        extra = {k: v for k, v in over.items() if k in ("walk_heat", "transfer_penalty")}
        one = {q: 1.0 for q in D.PURPOSES}   # per-purpose results at scale 1; each calibration's K applied once below
        r = prob.m.run(nets[s], s, K=one, track=False, **kw, **extra)
        r0 = prob.m.run(prob.base, s, K=one, track=False, **kw, **extra)
        for v, K in (("A", prob.cal["K"]), ("B", prob.cal["K_prior"])):
            c = sum(K[p] * r["cost_p"][p] for p in D.PURPOSES); c0 = sum(K[p] * r0["cost_p"][p] for p in D.PURPOSES)
            hc = sum(K[p] * r["home_cost"][p] for p in D.PURPOSES if p != "tourist")
            ht = sum(K[p] * r["home_trips"][p] for p in D.PURPOSES if p != "tourist")
            hc0 = sum(K[p] * r0["home_cost"][p] for p in D.PURPOSES if p != "tourist")
            ht0 = sum(K[p] * r0["home_trips"][p] for p in D.PURPOSES if p != "tourist")
            ar = prob.m.pts.area.values[prob.m.homes]
            area = (pd.Series(hc).groupby(ar).sum() / pd.Series(ht).groupby(ar).sum()) / \
                (pd.Series(hc0).groupby(ar).sum() / pd.Series(ht0).groupby(ar).sum())
            trips = sum(K[p] * r["trips"][p] for p in D.PURPOSES); trips0 = sum(K[p] * r0["trips"][p] for p in D.PURPOSES)
            out[(s, v)] = dict(cost=c / c0, area=area, trips=trips, trips0=trips0)
    return out


def main():
    tag = sys.argv[1]
    mode = "keep" if tag.startswith("keep") else ("moderate" if tag.startswith("moderate") else "full")
    peak_delta = -3 if "peak-3" in tag else 0
    prob = O.Problem(mode, peak_delta)
    state, seas, _ = load(tag)
    nets = {s: prob.network(seas[s] if seas else state) for s in P.SEASONS}
    res = eval_net(prob, nets)
    w = {s: P.SEASONS[s]["months"] / 12 for s in P.SEASONS}
    year = {v: sum(w[s] * res[(s, v)]["cost"] for s in P.SEASONS) for v in ("A", "B")}
    summary = {"tag": tag, "perceived_cost_vs_today": {f"{s}/{v}": round(res[(s, v)]["cost"], 4) for (s, v) in res},
               "year_A": round(year["A"], 4), "year_B": round(year["B"], 4),
               "bus_trips_vs_today": {f"{s}/{v}": round(res[(s, v)]["trips"] / res[(s, v)]["trips0"], 3) for (s, v) in res}}
    fl = {s: N.fleet(nets[s]) for s in P.SEASONS}; f0 = N.fleet(prob.base)
    summary["fleet"] = {s: dict(peak=max(b.values()), by_period=b, hours=round(h, 1)) for s, (b, h) in fl.items()}
    summary["fleet_today"] = dict(peak=max(f0[0].values()), by_period=f0[0], hours=round(f0[1], 1))
    # areas
    A = pd.DataFrame({f"{s}/{v}": res[(s, v)]["area"] for (s, v) in res})
    A["worst"] = A.max(axis=1); A["best"] = A.min(axis=1)
    A = A.join(prob.m.areas.set_index("stat11")[["pop", "Vehicle0_pcnt"]])
    A.round(3).to_csv(f"data/assess_{tag}_areas.csv")
    summary["worst_area"] = round(float(A.worst.max()), 3)
    # lines: winter network, boardings with tracking (calibration A and B)
    names = dict(zip(prob.sg.stops.stop_id, prob.sg.stops.stop_name, strict=True))
    r = prob.m.run(nets["winter"], "winter", K={q: 1.0 for q in D.PURPOSES}, track=True, **prob.kw)
    rows = []
    for i, p in enumerate(nets["winter"]):
        bA = sum(prob.cal["K"][q] * r["board"][q][i] for q in D.PURPOSES)
        bB = sum(prob.cal["K_prior"][q] * r["board"][q][i] for q in D.PURPOSES)
        rows.append(dict(pattern=p.name, line=p.line, start=names.get(p.stops[0], p.stops[0]), end=names.get(p.stops[-1], p.stops[-1]),
                         stops=len(p.stops) - len(p.skip), skipped=len(p.skip), run_min_midday=round(p.run_min("12-15"), 1),
                         **{f"hw_{s}_{q}": (seas[s][p.line][q] if seas and p.line in seas[s] else p.headway[q]) for s in P.SEASONS for q in P.PERIODS},
                         boardings_A=round(bA), boardings_B=round(bB)))
    L = pd.DataFrame(rows); L.to_csv(f"data/assess_{tag}_lines.csv", index=False)
    # travel times to key attractors at 09-12 (perceived minutes, min of bus and walking), today vs proposal
    tt = {}
    for label, net in (("today", prob.base), ("proposal", nets["winter"])):
        o = prob.m.ev.run(net, "09-12", sources=prob.m.homes)
        g = np.minimum(o["gc_bus"], o["walk"])
        cols = [prob.m.att[list(D.ATTRACTORS.name).index(k)] for k in KEY]
        t = pd.DataFrame(g[:, cols], columns=KEY).groupby(prob.m.pts.area.values[prob.m.homes]).median()
        tt[label] = t
    T = pd.concat(tt, axis=1).round(1); T.to_csv(f"data/assess_{tag}_traveltime.csv")
    # sensitivity: re-evaluate the same proposal under other values of every assumed number
    sens = {}
    tests = [("stop cost 20 s", dict(STOP_COST_S=20)), ("stop cost 40 s", dict(STOP_COST_S=40)),
             ("transfer penalty 10 min", dict(transfer_penalty=10.0)), ("walk/wait weight 1.5", dict(W_WALK=1.5, W_WAIT=1.5)),
             ("walk/wait weight 1.75", dict(W_WALK=1.75, W_WAIT=1.75)), ("heat weight 2.0", dict(walk_heat=2.0)),
             ("heat weight 3.0", dict(walk_heat=3.0)), ("logit scale 0.15", dict(lam=0.15)),
             ("car owners ride more (0.2)", dict(car_prop=0.2))]
    for name, over in tests:
        saved = {k: getattr(P, k) for k in over if hasattr(P, k)}
        for k, v in over.items():
            if hasattr(P, k):
                setattr(P, k, v)
        rr = eval_net(prob, nets, **over)
        for k, v in saved.items():
            setattr(P, k, v)
        sens[name] = {v: round(sum(w[s] * rr[(s, v)]["cost"] for s in P.SEASONS), 4) for v in ("A", "B")}
        sens[name]["worst_area"] = round(float(max(rr[k]["area"].max() for k in rr)), 3)
        print(name, sens[name], flush=True)
    summary["sensitivity"] = sens
    json.dump(summary, open(f"data/assess_{tag}.json", "w"), indent=1, default=float)
    print(json.dumps({k: v for k, v in summary.items() if k != "sensitivity"}, indent=1, default=float))
    print(L[["pattern", "start", "end", "stops", "skipped", "run_min_midday", "boardings_A", "boardings_B"]].to_string(index=False))
    plot(prob, nets["winter"], A, tag)


def plot(prob, pats, A, tag):
    areas = gpd.read_file("data/areas.geojson").set_index("stat11")
    st = prob.sg.stops.set_index("stop_id")
    fig, axes = plt.subplots(1, 2, figsize=(14, 8.5), dpi=140, facecolor="#fcfcfb")
    for ax, (title, net) in zip(axes, [("Today", prob.base), ("Proposal", pats)], strict=True):
        areas.plot(ax=ax, color="#efeeea", edgecolor="white", lw=.6)
        segs = {}
        for p in net:
            h = p.headway.get("09-12", math.inf)
            if not math.isfinite(h):
                continue
            xy = [(st.stop_lon[s], st.stop_lat[s]) for s in p.stops if s in st.index]
            for a, b in zip(xy[:-1], xy[1:], strict=True):
                k = tuple(sorted((a, b))); segs[k] = segs.get(k, 0) + 60 / h
        cmap = matplotlib.colormaps["Blues"]
        items = sorted(segs.items(), key=lambda x: x[1])
        lc = LineCollection([list(k) for k, _ in items], colors=[cmap(.35 + .65 * min(v, 12) / 12) for _, v in items],
                            linewidths=[.6 + 3.4 * min(v, 12) / 12 for _, v in items], capstyle="round")
        ax.add_collection(lc)
        ax.set_xlim(34.895, 34.985); ax.set_ylim(29.49, 29.59); ax.set_axis_off()
        ax.set_aspect(1 / np.cos(np.radians(29.55)))
        ax.set_title(f"{title}: buses an hour on each street, 09:00-12:00 (darker, thicker = more)", loc="left", fontsize=10)
    g = areas.join(A[["worst", "best"]])
    g["mid"] = (g.worst + g.best) / 2
    ax = axes[1]
    for r in g.dropna(subset=["mid"]).itertuples():
        c = r.geometry.representative_point()
        ax.annotate(f"{(r.mid - 1) * 100:+.0f}%", (c.x, c.y), ha="center", fontsize=7, color="#0b0b0b",
                    bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="none", alpha=.7))
    fig.text(.01, .01, "Labels: change in perceived door-to-door time per trip for the area's residents (negative = better), "
             "average over seasons and calibrations.", fontsize=8, color="#52514e")
    fig.tight_layout(); fig.savefig(f"figs/proposal_{tag}.png")


if __name__ == "__main__":
    main()
