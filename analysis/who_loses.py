"""Each origin (residential areas and places) on the recommended network against today, per season, on unseen
delay draws (check_tt.SEEDS). Output: data/who_loses.json {season: {origin: % change}}.
Usage: MODE=design PYTHONPATH=.:scripts:analysis python3 analysis/who_loses.py data/net_F2.json"""
import json
import os
import sys

import numpy as np

import check_tt as C
import optimize_tt as X
import timetable_offsets as T
from eilat import demand as Dm


def main():
    path, out = sys.argv[1], {}
    att = {(float(a), float(b)): n for n, a, b in zip(Dm.ATTRACTORS.name, Dm.ATTRACTORS.lat, Dm.ATTRACTORS.lon, strict=True)}
    for season in ("winter", "summer"):
        os.environ["OD"] = "demand"; os.environ["SEASON"] = season
        S = X.Search(); pts = S.prob.m.pts
        today = T.TodayNet(); today.foot = S.tt.foot
        nets = {"today": today.network(today.start), "plan": C.PatsNet(S.tt, S.prob.network(C.load(S, path))).network(None)}
        res = {k: S.tt.per_home(n, "holdout", C.SEEDS)[0] for k, n in nets.items()}
        def name(o):
            if (o[0], o[1]) in att:
                return att[(o[0], o[1])]
            return "area " + str(int(pts.area.values[int(np.argmin((pts.lat.values - o[0]) ** 2 + (pts.lon.values - o[1]) ** 2))]))
        out[season] = dict(sorted(((name(o), round((res["plan"][o] / res["today"][o] - 1) * 100, 1)) for o in res["today"]),
                                  key=lambda r: -r[1]))
        print(season, list(out[season].items())[:8], flush=True)
    json.dump(out, open("data/who_loses.json", "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
