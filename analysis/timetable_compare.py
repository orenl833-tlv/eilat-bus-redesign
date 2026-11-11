"""Today and the three options on the timetable, all timed the same way (winter weekday 07-21).

Each network is planned as buses really run (analysis/timetable_offsets.py): street segments at the GPS-measured
time of that hour and direction, every trip delayed as a real trip of its line, direction and hour was
(N_SEEDS draws), the rider seeing actual departures and needing 2 minutes at a transfer, leaving home at random
times within every hour. Trips: each area's centre to each key place at least 15 minutes' walk away, weighted
by the area's residents (the same trips for every network).

Also the frequency-based model's perceived time on the same trips (the model the options were chosen with:
wait = half the combined headway, line-level run-time factors), to show where the two disagree.

Usage: PYTHONPATH=.:scripts python3 analysis/timetable_compare.py   Output: data/timetable_compare.json
"""
import json

import numpy as np

import blocking as BL
import timetable_offsets as T
from eilat import params as P
from eilat.evaluate import walk_min

TAGS = {"keep": "1 · keep every line", "full_warm": "2 · restructure", "full_peak-3_warm": "3 · restructure, fewer buses"}
SEEDS, P_SEEDS = range(300, 310), range(400, 403)
HOURS_IN = {"06-09": 2, "09-12": 3, "12-15": 3, "15-19": 4, "19-24": 2}   # hours of each period inside 07-21


def freq_perceived(S, pats):
    """The frequency model's perceived minutes on the same trips (walk if quicker), periods weighted by hours."""
    m = T.O.Problem("full").m
    pts = m.pts
    tot = wsum = 0.0
    homes = sorted({o for o, *_ in S.od})
    idx = [int(np.argmin((pts.lat.values - o[0]) ** 2 + (pts.lon.values - o[1]) ** 2)) for o in homes]
    for q, nh in HOURS_IN.items():
        r = m.ev.run(pats, q, w_walk=P.W_WALK, sources=idx)
        for o, d, w, wd in S.od:
            i = homes.index(o)
            a = int(np.argmin((pts.lat.values - d[0]) ** 2 + (pts.lon.values - d[1]) ** 2))
            v = min(r["gc_bus"][i, a], P.W_WALK * float(walk_min(o[0], o[1], d[0], d[1])))
            tot += w * nh * v; wsum += w * nh
    return tot / wsum


def main():
    today = T.TodayNet()
    foot = today.network(today.start)[0].foot
    nets = {"today": ("today", today, T.O.Problem("full").base)}
    for tag, label in TAGS.items():
        S = T.PlanNet(tag); S.foot = foot
        nets[tag] = (label, S, BL.option_net(tag, T.SEASON))
    res = {}
    for k, (label, S, pats) in nets.items():
        res[k] = dict(label=label,
                      minutes=round(S.score(S.start, T.HOLDOUT_LEAVE, None, SEEDS), 2),
                      perceived=round(S.perceived(S.start, T.HOLDOUT_LEAVE, P_SEEDS), 2),
                      freq_model_perceived=round(freq_perceived(S, pats), 2),
                      buses=S.buses(S.start))
        print(k, res[k], flush=True)
    for k in TAGS:
        for m in ("minutes", "perceived", "freq_model_perceived"):
            res[k][m + "_vs_today"] = round(res[k][m] / res["today"][m] - 1, 4)
    json.dump(res, open("data/timetable_compare.json", "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
