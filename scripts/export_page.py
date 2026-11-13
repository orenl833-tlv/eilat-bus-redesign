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

OPTS = {"today": "Today", "net_F2": "Recommended network"}
# the recommended network's numbers come from the timetable check (analysis/page_tt.py), not the frequency model
PAGE_TT = "data/page_tt.json"


EVENING_END = 23   # the recommended package: evening service ends at 23:00 (scripts/evening.py)


def nets(prob, tag, evening_end=None):
    """Season -> network. With evening_end, an option's evening is shortened as the evaluation sees it
    (scripts/evening.py: the 19-24 average headway stretched)."""
    if tag == "today":
        return {s: prob.base for s in P.SEASONS}
    if tag.startswith("net_"):
        import blocking as BL
        import evening as EV
        n = BL.option_net(tag, "winter")
        return {s: (EV.thinned(n, evening_end) if evening_end else n) for s in P.SEASONS}
    if evening_end:
        import evening as EV
        return {s: EV.thinned(n, evening_end) for s, n in nets(prob, tag).items()}
    sr = json.load(open(f"data/opt_{tag}_seasonal.json"))
    return {s: prob.network({k: {q: (h if h is not None else math.inf) for q, h in v.items()} for k, v in sr[s].items()})
            for s in P.SEASONS}


# public names: a variant keeps its line's number; a line invented by the search gets a free urban number
NEW_LINE_NAMES = {"A14H": ("7", "קו חדש: קמפוס – תחנה מרכזית – מלונות"),   # the old plan's new line
                  # the recommended network's lines designed from scratch (data/net_F2.json)
                  "D28805_42115": ("7", "קו חדש: מלונות החוף הצפוני – דרך הבשמים"),
                  "D12719_42115": ("8", "קו חדש: מרכז ביג – דרך הבשמים"),
                  "D12157_12356": ("9", "קו חדש: שחמון/קטורה – עירייה"),
                  # net_H's (an earlier candidate)
                  "D12169_28805": ("7", "קו חדש: ברנע – מלונות החוף הצפוני"),
                  "D28809_29186": ("9", "קו חדש: קניון אייס מול – תיכון בגין")}
VARIANT_HE = {"x": "מדלג על תחנות שקטות", "s": "מסלול מקוצר"}


def public_name(line):
    if line in NEW_LINE_NAMES:
        return NEW_LINE_NAMES[line]
    base = line.rstrip("xs")
    note = VARIANT_HE.get(line[len(base):], "")
    return base, note


def lines(net, sid, names):
    """Each line pattern: name, start and end stop names, the stop indices it passes (skipped ones flagged) and
    its headway per period."""
    out = []
    for p in net:
        if all(not math.isfinite(p.headway.get(q, math.inf)) for q in P.PERIODS):
            continue
        disp, note = public_name(p.line)
        out.append(dict(name=p.name, line=p.line, display=disp, note=note, start=names.get(p.stops[0], ""), end=names.get(p.stops[-1], ""),
                        stops=[sid[x] for x in p.stops if x in sid], skip=[sid[x] for x in p.skip if x in sid],
                        hw={q: (round(p.headway[q]) if math.isfinite(p.headway.get(q, math.inf)) else None) for q in P.PERIODS}))
    return out


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


def active():
    """Lines running, departures and buses out in each hour (from scripts/active_lines.py)."""
    A = pd.read_csv("data/active_lines.csv")
    A = A[A.hour < 24]   # nothing leaves after midnight
    return {"hours": sorted(A.hour.unique().tolist()),
            "data": {t: {se: {c: g[c].tolist() for c in ["lines", "departures", "buses_out"]} for se, g in d.groupby("season")}
                     for t, d in A.sort_values("hour").groupby("option")}}


def poi_flows():
    """People arriving at / leaving each key place by bus, per network, season and period (and the whole day),
    from the model (calibration A); plus each place's assumed size (jobs, students, leisure and tourist weights)."""
    from eilat import demand as Dm
    probs = {"full": O.Problem("full"), "keep": O.Problem("keep")}
    names = list(Dm.ATTRACTORS.name)
    out = {"places": names, "size": Dm.ATTRACTORS[["jobs", "school", "leisure", "tourist"]].values.tolist(), "flow": {}}
    for tag in OPTS:
        prob = probs["keep" if tag == "keep" else "full"]
        ns = nets(prob, tag, EVENING_END)
        out["flow"][tag] = {}
        for se in P.SEASONS:
            r = prob.m.run(ns[se], se, K=prob.cal["K"], track=False, **prob.kw)
            per = {q: r["att_flow"][q][:, [1, 3]].round().astype(int).tolist() for q in P.PERIODS}
            per["all"] = sum(r["att_flow"][q][:, [1, 3]] for q in P.PERIODS).round().astype(int).tolist()
            out["flow"][tag][se] = per
    return out


def main():
    os.makedirs("web", exist_ok=True)
    prob_full = O.Problem("full"); prob_keep = O.Problem("keep")
    stops = prob_full.sg.stops.reset_index(drop=True)
    sid = {s: i for i, s in enumerate(stops.stop_id)}
    out = {"stops": [[round(r.stop_lat, 5), round(r.stop_lon, 5), r.stop_name] for r in stops.itertuples()],
           "periods": list(P.PERIODS), "seasons": list(P.SEASONS), "options": OPTS, "net": {}, "areas": [], "summary": {}}
    from eilat.demand import areas as model_areas
    a = model_areas()[0]   # the model's residents: 2020 polygons scaled to the 2022 census, area 16 split from 15
    a["geometry"] = a.geometry.simplify(0.0001)
    for r in a.itertuples():
        geom = r.geometry.geoms if r.geometry.geom_type == "MultiPolygon" else [r.geometry]
        rings = [[[round(x, 5), round(y, 5)] for x, y in g.exterior.coords] for g in geom]
        out["areas"].append(dict(id=int(r.stat11), rings=rings, pop=None if pd.isna(r.pop) else int(round(r.pop, -1)),
                                 nocar=None if pd.isna(r.Vehicle0_pcnt) else float(r.Vehicle0_pcnt)))
    for tag in OPTS:
        prob = prob_keep if tag == "keep" else prob_full
        ns = nets(prob, tag, EVENING_END)
        out["net"][tag] = {s: {q: segments(ns[s], q, sid) for q in P.PERIODS} for s in P.SEASONS}
        names = dict(zip(stops.stop_id, stops.stop_name, strict=True))
        # line lists keep the real headways (the 19-24 column then means 19-23)
        out.setdefault("lines", {})[tag] = {s: lines(nets(prob, tag)[s], sid, names) for s in P.SEASONS}
        if tag.startswith("net_"):
            pt = json.load(open(PAGE_TT))
            fp = pt["fleet"]["plan"]
            out["summary"][tag] = dict(year_A=round(pt["city"]["year"], 4), year_B=round(pt["city"]["year"], 4),
                                       worst_area=round(1 + max(pt["area"]["year"].values()) / 100, 3),
                                       peak={s: fp["buses"] for s in list(P.SEASONS) + ["year"]},
                                       hours={s: fp["bus_hours"] for s in list(P.SEASONS) + ["year"]},
                                       area=pt["area"]["year"], season={k: round(v, 4) for k, v in pt["city"].items()},
                                       drivers=fp["drivers_overtime"], source="timetable")
        elif tag != "today":
            import assess as AS
            from eilat import network as N
            res = AS.eval_net(prob, ns)
            w = {s: P.SEASONS[s]["months"] / 12 for s in P.SEASONS}
            year = {v: sum(w[s] * res[(s, v)]["cost"] for s in P.SEASONS) for v in ("A", "B")}
            A = pd.DataFrame({f"{s}/{v}": res[(s, v)]["area"] for (s, v) in res})
            fl = {s: N.fleet(ns[s]) for s in P.SEASONS}
            out["summary"][tag] = dict(
                year_A=round(year["A"], 4), year_B=round(year["B"], 4), worst_area=round(float(A.max(axis=1).max()), 3),
                peak={s: max(b.values()) for s, (b, h) in fl.items()}, hours={s: round(h, 1) for s, (b, h) in fl.items()},
                area={str(int(i)): round(float((r.max() + r.min()) / 2 - 1) * 100, 1) for i, r in A.iterrows()})
    # door-to-door minutes from each residential area's centre to the key places (timetable check, the same
    # timetable in every season), for today and the recommended network
    pt = json.load(open(PAGE_TT))
    out["tt"] = {}
    for tag in OPTS:
        src = pt["tt"]["today" if tag == "today" else "plan"]
        out["tt"][tag] = {se: {q: {a: row[q] for a, row in src.items() if q in row} for q in list(P.PERIODS) + ["all"]}
                          for se in P.SEASONS}
    out["tt_keys"] = pt["keys"]
    out["active"] = active()
    # absolute level of service per area (analysis/service_los.py): each map against fixed targets
    if os.path.exists("data/service_los.json"):
        out["los"] = json.load(open("data/service_los.json"))
    out["poi_flow"] = poi_flows()
    ft = json.load(open(PAGE_TT))["fleet"]["today"]
    out["summary"]["today"] = dict(peak=ft["buses"], hours=ft["bus_hours"], drivers=ft["drivers_overtime"])
    # base map: the city's whole area (land), the gulf (frame south of North Beach minus the city; the city's boundary
    # there follows the shore), and landmarks
    from shapely.geometry import Point, box
    from shapely.ops import unary_union
    allareas = gpd.read_file("data/areas.geojson")
    land = unary_union(list(allareas.geometry)).buffer(0)
    ring = lambda g: [[round(x, 5), round(y, 5)] for x, y in g.exterior.coords]  # noqa: E731
    out["land"] = [ring(g.simplify(0.00008)) for g in (land.geoms if land.geom_type == "MultiPolygon" else [land])]
    sea = box(34.900, 29.492, 34.985, 29.552).difference(land)
    parts = list(sea.geoms) if sea.geom_type == "MultiPolygon" else [sea]
    corner = Point(34.984, 29.493)
    sea_part = min(parts, key=lambda g: g.distance(corner))
    out["sea"] = [ring(sea_part.simplify(0.0002))]
    out["pois"] = [
        ["בית החולים יוספטל", 29.5549, 34.9401, "health"], ["חוף האלמוגים", 29.5082, 34.9207, "beach"],
        ["חוף הדקל", 29.5413, 34.9470, "beach"], ["המלונות והחוף הצפוני", 29.5535, 34.9625, "hotel"],
        ["קניון אייס מול", 29.5549, 34.9661, "shop"], ["קניון מול הים", 29.5511, 34.9550, "shop"],
        ["מרכז ביג", 29.5677, 34.9596, "shop"], ["קמפוס אילת", 29.5665, 34.9522, "school"],
        ["תיכון רבין", 29.5534, 34.9358, "school"], ["תיכון בגין", 29.5622, 34.9379, "school"],
        ["תיכון גולדווטר", 29.5536, 34.9481, "school"], ["עירייה", 29.5561, 34.9520, "civic"],
        ["התחנה המרכזית (Star Eilat)", 29.5577, 34.9536, "terminal"], ["חנה וסע, כניסה לעיר", 29.5713, 34.9623, "terminal"],
        ["חניון אגד", 29.5742, 34.9612, "depot"], ["נמל אילת", 29.5355, 34.9404, "port"],
        ["מעבר טאבה", 29.4931, 34.9051, "border"], ["מעבר רבין", 29.5818, 34.9698, "border"],
    ]
    json.dump(out, open("web/data.json", "w"), ensure_ascii=False, separators=(",", ":"))
    print("web/data.json", round(os.path.getsize("web/data.json") / 1e3), "kB")



if __name__ == "__main__":
    main()
