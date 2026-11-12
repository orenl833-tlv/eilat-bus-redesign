"""How much does knowing the future flatter a network? Riders planned clairvoyantly (they know every delay
before leaving, as in the search) against riders who commit to a first line from the timetable and then live
with the delays (eilat/timetable.py Network.committed): a missed connection costs them a wait for the next bus.
Today's real timetable and a network state; the residents' trips (areas x key places), new leaving times and
delay draws. Also the share of trips with a transfer, and how often the committed rider loses more than 5 min.

Usage: MODE=design PYTHONPATH=.:scripts:analysis python3 analysis/committed_rider.py data/net_H.json
Output: data/committed_rider.json
"""
import json
import sys

import numpy as np


import check_tt as C
import optimize_tt as X
import timetable_offsets as T

SEEDS = range(1500, 1504)


def main():
    S = X.Search()
    today = T.TodayNet(); today.foot = S.tt.foot
    nets = {"today": today.network(today.start)[0],
            "plan": C.PatsNet(S.tt, S.prob.network(C.load(S, sys.argv[1]))).network(None)[0]}
    out = {}
    for name, net in nets.items():
        clair, comm, w, lost5, transfers = 0.0, 0.0, 0.0, 0.0, 0.0
        reals = [net.realize(S.tt.sampler, s, None) for s in SEEDS]
        by_home = {}
        for o, d, wt, wd in S.tt.od:
            by_home.setdefault(o, []).append((d, wt, wd))
        for o, ds in by_home.items():
            for t0 in T.leave_times(o, "holdout")[::2]:
                dl = [d for d, _, _ in ds]
                schs = net.plan_many(o[0], o[1], dl, t0, T.TRANSFER_MIN)          # one scan per origin and time
                for real in reals:
                    knows = real.arrivals(o[0], o[1], dl, t0, T.TRANSFER_MIN)
                    for (d, wt, wd), sch, ka in zip(ds, schs, knows, strict=True):
                        nride = sum(1 for g in sch["legs"] if g[0] == "ride") if sch and sch["arrive"] - t0 < wd else 0
                        a = wd if not np.isfinite(ka) else min(ka - t0, wd)
                        c = real.committed(net, o[0], o[1], d[0], d[1], t0, T.TRANSFER_MIN, sch) if nride else None
                        b = wd if c is None else min(c - t0, wd)
                        clair += wt * a; comm += wt * b; w += wt
                        lost5 += wt * (b - a > 5); transfers += wt * (nride >= 2)
        out[name] = dict(clairvoyant=round(clair / w, 2), committed=round(comm / w, 2), gap=round((comm - clair) / w, 2),
                         lose_5min_share=round(lost5 / w, 3), transfer_share=round(transfers / w, 3))
        print(name, out[name], flush=True)
    out["plan_vs_today"] = dict(clairvoyant=round(out["plan"]["clairvoyant"] / out["today"]["clairvoyant"] - 1, 4),
                                committed=round(out["plan"]["committed"] / out["today"]["committed"] - 1, 4))
    print(out["plan_vs_today"])
    json.dump(out, open("data/committed_rider.json", "w"), indent=1)


if __name__ == "__main__":
    main()
