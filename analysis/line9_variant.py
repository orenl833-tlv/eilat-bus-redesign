"""Line 9 of net_F2 (D12157_12356) runs out the long way (Shahamon - Argaman - central station - city hall - hotels
loop - city hall) and back the short way (city hall - Eilot - Shahamon): in effect a one-way loop. This builds
two-way alternatives from the same stop graph (fastest path each way along streets buses drive today, as
eilat.candidates.designed_lines does) and checks net_F2 with line 9 replaced by each, at line 9's headways,
on unseen leaving times and delay draws (as scripts/check_tt.py).

Usage: MODE=design OD=demand SEASON=winter PYTHONPATH=.:scripts:analysis python3 analysis/line9_variant.py
Output: data/line9_variant_<season>.json
"""
import json
import math
import os

import check_tt as C
import optimize_tt as X
import timetable_offsets as T
from eilat import candidates as CD
from eilat import network as EN

SHAHAMON = 12157
ENDS = {"city hall (north side)": 12625, "city hall (as now)": 12356, "central station": 49812}
OLD = "D12157_12356"


def main():
    season = os.environ.get("SEASON", "winter")
    S = X.Search(); prob = S.prob; sg = prob.sg
    names = prob.sg.stops.set_index("stop_id").stop_name.to_dict() if hasattr(sg, "stops") else {}
    path = "data/net_F2_summer.json" if season == "summer" else "data/net_F2.json"
    base = C.load(S, path)
    hw9 = base[OLD]
    today = T.TodayNet(); today.foot = S.tt.foot
    thb, (tm, tp) = S.tt.per_home(today.network(today.start), "holdout", C.SEEDS, metric="both")
    th = {o: v[0] for o, v in thb.items()}

    def check(st):
        pats = prob.network(st)
        N = C.PatsNet(S.tt, pats)
        hb, (m, pm) = S.tt.per_home(N.network(None), "holdout", C.SEEDS, metric="both")
        _, hours = EN.fleet(pats)
        return dict(minutes=m, vs_today=m / tm - 1, perceived_vs_today=pm / tp - 1,
                    worst_area=max(hb[o][0] / th[o] for o in hb), buses=N.buses(None), bus_hours=hours)

    out = {"season": season, "net_F2": check(base)}
    print("net_F2", out["net_F2"], flush=True)
    for label, end in ENDS.items():
        f, r = sg.path(SHAHAMON, end), sg.path(end, SHAHAMON)
        if f is None or r is None:
            print(label, "no path"); continue
        run = lambda s: sum(sg.edge_min.get((u, v), 1.0) for u, v in zip(s[:-1], s[1:], strict=True))  # noqa: E731
        info = dict(out_stops=[names.get(s, s) for s in f], back_stops=[names.get(s, s) for s in r],
                    out_min=round(run(f), 1), back_min=round(run(r), 1))
        print(label, info, flush=True)
        if end == ENDS["city hall (as now)"]:
            out[label] = info; continue          # the current line 9: listed for its paths only
        name = f"V9_{end}"
        prob.lines[name] = [CD.make(sg, f"{name}/0", name, f), CD.make(sg, f"{name}/1", name, r)]
        prob.family[name] = name
        st = dict(base); st[OLD] = {q: math.inf for q in hw9}; st[name] = dict(hw9)
        info.update(check(st))
        out[label] = info
        print(label, {k: v for k, v in info.items() if not k.endswith("stops")}, flush=True)
    json.dump(out, open(f"data/line9_variant_{season}.json", "w"), ensure_ascii=False, indent=1, default=float)


if __name__ == "__main__":
    main()
