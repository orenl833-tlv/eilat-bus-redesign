"""Numbers for the map page (web/eilat.html) from the timetable check, for today and the recommended network.

- area change: each residential area's demand-weighted door-to-door minutes (its centre to the key places and
  back, scripts/optimize_tt.py OD=demand), the network against today, per season (spring/autumn uses the
  winter trips: same timetable and no summer tourism peak);
- travel times: door-to-door minutes from each area's centre to the page's key places, per period and the whole
  day (periods weighted by hours), mean over leaving times in the period and SEEDS delay draws;
- summary: the whole-city change per season and over the year (by months), the worst area, buses and
  bus-hours with 15% terminal recovery (data/fleet_tt.json).
All timetables are timed the same way (GPS run times per street segment, hour and direction; real delays).

Usage: MODE=design PYTHONPATH=.:scripts:analysis python3 analysis/page_tt.py data/net_H.json   Output: data/page_tt.json
"""
import json
import os
import random
import sys

import numpy as np

import check_tt as C
import optimize_tt as X
import timetable_offsets as T
from eilat import demand as Dm
from eilat import params as P
from eilat.timetable import _period

KEYS = ["City hall / centre", "Old central station (Star Eilat)", "Hotels, North Beach", "Big centre", "Yoseftal hospital", "Coral Beach"]
SEEDS = range(1100, 1104)
PER_HOUR = 3


def area_of(pts, o):
    return str(int(pts.area.values[int(np.argmin((pts.lat.values - o[0]) ** 2 + (pts.lon.values - o[1]) ** 2))]))


def main():
    path = sys.argv[1]
    out = {"area": {}, "city": {}, "tt": {}}
    for season in ("winter", "summer"):
        os.environ["OD"] = "demand"; os.environ["SEASON"] = season
        S = X.Search()
        pts = S.prob.m.pts
        today = T.TodayNet(); today.foot = S.tt.foot
        nets = {"today": today.network(today.start), "plan": C.PatsNet(S.tt, S.prob.network(C.load(S, path))).network(None)}
        res = {k: S.tt.per_home(n, "holdout", C.SEEDS) for k, n in nets.items()}
        homes = [o for o in res["today"][0] if (o[0], o[1]) not in {(float(a), float(b)) for a, b in zip(Dm.ATTRACTORS.lat, Dm.ATTRACTORS.lon, strict=True)}]
        out["area"][season] = {area_of(pts, o): round((res["plan"][0][o] / res["today"][0][o] - 1) * 100, 1) for o in homes}
        out["city"][season] = res["plan"][1] / res["today"][1]
        if season == "winter":
            att = Dm.ATTRACTORS
            dests = [(float(att.lat[list(att.name).index(k)]), float(att.lon[list(att.name).index(k)])) for k in KEYS]
            hours = {q: len([h for h in range(6, 23) if a <= h < b]) for q, (a, b) in P.PERIODS.items()}
            for k, (net, keys) in nets.items():
                out["tt"][k] = {}
                reals = [net.realize(S.tt.sampler, s, keys) for s in SEEDS]
                for o in homes:
                    rng = random.Random(f"page|{o}")
                    per = {q: np.zeros(len(KEYS)) for q in P.PERIODS}; n = {q: 0 for q in P.PERIODS}
                    for h in range(6, 23):
                        for _ in range(PER_HOUR):
                            t0 = h * 60 + rng.random() * 60; q = _period(t0)
                            for real in reals:
                                arr = real.arrivals(o[0], o[1], dests, t0, T.TRANSFER_MIN)
                                wd = [float(X.walk_min(o[0], o[1], d[0], d[1])) for d in dests]
                                per[q] += [w if not np.isfinite(a) else min(a - t0, w) for a, w in zip(arr, wd, strict=True)]
                                n[q] += 1
                    row = {q: [round(float(v) / n[q], 1) for v in per[q]] for q in P.PERIODS if n[q]}
                    row["all"] = [round(sum(row[q][i] * hours[q] for q in row) / sum(hours[q] for q in row), 1) for i in range(len(KEYS))]
                    out["tt"][k][area_of(pts, o)] = row
    w = {s: P.SEASONS[s]["months"] / 12 for s in P.SEASONS}
    city = {"winter": out["city"]["winter"], "spring_autumn": out["city"]["winter"], "summer": out["city"]["summer"]}
    out["city"]["year"] = sum(w[s] * city[s] for s in P.SEASONS)
    out["area"]["year"] = {a: round(sum(w[s] * out["area"]["winter" if s != "summer" else "summer"][a] for s in P.SEASONS), 1)
                           for a in out["area"]["winter"]}
    out["keys"] = KEYS
    fl = json.load(open("data/fleet_tt.json"))
    out["fleet"] = {"today": fl["today@0.15"], "plan": fl[f"{path}@0.15"]}
    json.dump(out, open("data/page_tt.json", "w"), ensure_ascii=False, indent=1)
    print({k: v for k, v in out["city"].items()}, "worst area", max(out["area"]["year"].values()))


if __name__ == "__main__":
    main()
