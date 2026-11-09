"""Shifolei HaHar (planned district, north-west): a spur into it from lines 5 and 6, with 3 new stops.

The district's streets aren't available (OpenStreetMap downloads are blocked from here), so the spur is an
assumption: from the nearest existing stops on Yahel St. (29093 on the 5 family, 29103 on the 6 family) out to
the district's reported centre and back, 3 stops evenly spaced. Run time: straight line x DETOUR at 25 km/h plus
STOP_COST_S at each new stop. Evaluated under the future demand (EILAT_FUTURE=1): with vs without the spur,
for each option, and the extra buses / bus-hours it needs.

Usage: PYTHONPATH=.:scripts python3 scripts/spur.py   Output: data/spur.json
"""
import json
import math
import os

import numpy as np
import pandas as pd

CENTRE = (29.5680, 34.9260)
ANCHORS = {29093: "5", 29103: "6"}   # stop -> family whose patterns get the spur
NEW_IDS = [990001, 990002, 990003]


def make_stops():
    st = pd.read_csv("data/stops_all.csv").set_index("stop_id")
    a = st.loc[29093]
    rows = []
    for i, sid in enumerate(NEW_IDS, start=1):
        f = i / 3
        rows.append(dict(stop_id=sid, stop_code=0, stop_name=f"Shifolei HaHar {i} (new)",
                         stop_lat=a.stop_lat + f * (CENTRE[0] - a.stop_lat), stop_lon=a.stop_lon + f * (CENTRE[1] - a.stop_lon)))
    pd.DataFrame(rows).to_csv("data/shifolei_stops.csv", index=False)
    return pd.concat([st.reset_index(), pd.DataFrame(rows)], ignore_index=True).set_index("stop_id")


def main():
    allst = make_stops()
    os.environ["EILAT_FUTURE"] = "1"; os.environ["EILAT_NEW_STOPS"] = "data/shifolei_stops.csv"
    import copy

    import optimize as O
    from eilat import network as N
    from eilat import params as P
    from eilat.evaluate import walk_min

    def seg(u, v):
        a, b = allst.loc[u], allst.loc[v]
        km = walk_min(a.stop_lat, a.stop_lon, b.stop_lat, b.stop_lon) * (P.WALK_KMH / 60)  # includes DETOUR
        return km / 25 * 60 + P.STOP_COST_S / 60

    def add_spur(pats):
        out = []
        for p in pats:
            fam = p.line[0] if p.line else ""
            anchor = next((s for s, f in ANCHORS.items() if s in p.stops and fam == f and not p.line.startswith(("80", "81", "82"))), None)
            if anchor is None:
                out.append(p); continue
            q = copy.deepcopy(p); i = q.stops.index(anchor)
            loop = [anchor] + NEW_IDS + NEW_IDS[-2::-1] + [anchor]
            extra = [seg(u, v) for u, v in zip(loop[:-1], loop[1:], strict=True)]
            q.stops = q.stops[:i] + loop + q.stops[i + 1:]
            for per in q.seg_min:
                q.seg_min[per] = list(q.seg_min[per][:i]) + extra + list(q.seg_min[per][i:])
            out.append(q)
        return out

    res = {}
    for tag in ["keep", "full_warm", "full_peak-3_warm"]:
        prob = O.Problem("keep" if tag == "keep" else "full", -3 if "peak-3" in tag else 0)
        sr = json.load(open(f"data/opt_{tag}_seasonal.json"))
        r = {}
        for label, f in (("without", lambda x: x), ("with spur", add_spur)):
            tot = {"A": 0.0, "B": 0.0}; district = []
            fl = []
            for s in P.SEASONS:
                st = {k: {q: (h if h is not None else math.inf) for q, h in v.items()} for k, v in sr[s].items()}
                net = f(prob.network(st))
                fl.append(N.fleet(net))
                O.SEASONS[:] = [s]
                ev = prob.raw(net)
                for v in ("A", "B"):
                    c, area = ev[(s, v)]; c0, area0 = prob.base_eval[(s, v)]
                    tot[v] += P.SEASONS[s]["months"] / 12 * c / c0
                    district.append(float(area.get(902, np.nan) / area0.get(902, np.nan)))
            O.SEASONS[:] = list(P.SEASONS)
            r[label] = dict(vs_today_A=round(tot["A"], 4), vs_today_B=round(tot["B"], 4),
                            district_902_vs_today=round(float(np.nanmean(district)), 3),
                            peak=max(max(b.values()) for b, _ in fl), hours=round(float(np.mean([h for _, h in fl])), 1))
        res[tag] = r
        print(tag, json.dumps(r), flush=True)
    json.dump(res, open("data/spur.json", "w"), indent=1)


if __name__ == "__main__":
    main()
