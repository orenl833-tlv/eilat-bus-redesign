"""Today vs the recommended network for a rider with a live bus app (eilat/app_rider.py), on demand-weighted trips.

For each delay draw (the same draws for both networks), each trip origin and each leaving time (one random time an hour
per origin, 06:00-22:59), every destination is travelled as an app rider would, and also by a rider who knows every
delay in advance (the earlier yardstick). Reports, per network: mean door-to-door minutes (both riders), the mean wait at
transfer stops, the share of trips the app rider makes more than 5 min slower than the all-knowing rider; and the change
against today with a 95% interval from the spread between draws.

Usage: MODE=design OD=demand SEASON=winter PYTHONPATH=.:scripts:analysis python3 analysis/app_rider.py data/net_F2.json
Output: data/app_rider_<season>.json
"""
import json
import os
import random
import sys

import numpy as np

import check_tt as C
import optimize_tt as X
import timetable_offsets as T
from eilat.app_rider import AppRider
from eilat.timetable import _period

SEEDS = range(1900, 1910)


def run(S, net, keys, seed):
    real = net.realize(S.tt.sampler, seed, keys)
    rider = AppRider(net, real, T.TRANSFER_MIN)
    tot = dict(app=0.0, know=0.0, xwait=0.0, slow5=0.0, w=0.0)
    for o in S.tt.homes:
        ds = S.tt.dod[o]
        rng = random.Random(f"app|{o}|{seed}")
        for h in X.HOURS:
            t0 = h * 60 + rng.random() * 60
            q = _period(t0)
            for d, wd, wq in ds:
                w = wq[q] / max(X.hours_in(q), 1)
                if w <= 0:
                    continue
                r = real.plan(o[0], o[1], d[0], d[1], t0, T.TRANSFER_MIN)
                know = wd if r is None else min(r["arrive"] - t0, wd)
                arr, xw = rider.trip(o[0], o[1], d[0], d[1], t0)
                app = min(arr - t0, wd)
                tot["app"] += w * app; tot["know"] += w * know; tot["xwait"] += w * xw
                tot["slow5"] += w * (app - know > 5); tot["w"] += w
    return {k: v / tot["w"] for k, v in tot.items() if k != "w"}


def main():
    path = sys.argv[1]
    season = os.environ.get("SEASON", "winter")
    S = X.Search()
    today = T.TodayNet(); today.foot = S.tt.foot
    nets = {"today": today.network(today.start), "plan": C.PatsNet(S.tt, S.prob.network(C.load(S, path))).network(None)}
    per = {k: [] for k in nets}
    for seed in SEEDS:
        for k, (net, keys) in nets.items():
            per[k].append(run(S, net, keys, seed))
        print(seed, {k: {m: round(v, 2) for m, v in per[k][-1].items()} for k in nets}, flush=True)
    out = {"season": season, "plan": path, "draws": len(SEEDS)}
    for k in nets:
        out[k] = {m: round(float(np.mean([r[m] for r in per[k]])), 3) for m in per[k][0]}
    for m in ("app", "know"):
        d = np.array([p[m] / t[m] - 1 for p, t in zip(per["plan"], per["today"], strict=True)])
        out[f"change_{m}"] = dict(mean=round(float(d.mean()), 4), ci95=round(float(1.96 * d.std(ddof=1) / np.sqrt(len(d))), 4))
    print(json.dumps(out, ensure_ascii=False), flush=True)
    json.dump(out, open(f"data/app_rider_{season}.json", "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
