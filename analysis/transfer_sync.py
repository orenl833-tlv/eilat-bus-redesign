"""Are connections timed? For every residential area (its point nearest the centre) x key place x departure
from home every 30 min (07:00-20:30), the trip is planned on the real timetable (eilat/timetable.py), today
and in the recommended plan. For trips with a transfer: the wait at the transfer stop = next bus's departure -
(arrival + walk between stops). Weighted by the area's residents.

Usage: PYTHONPATH=.:scripts python3 analysis/transfer_sync.py   Output: data/transfer_sync.json
"""
import json

import numpy as np
import pandas as pd

import optimize as O
from eilat import demand as Dm
from eilat.evaluate import walk_min
from eilat.timetable import Network


def waits(net, o, d, t0):
    r = net.plan(o[0], o[1], d[0], d[1], t0)
    if r is None:
        return None
    rides = [i for i, leg in enumerate(r["legs"]) if leg[0] == "ride"]
    out = []
    for a, b in zip(rides[:-1], rides[1:], strict=True):
        walk = sum(leg[1] for leg in r["legs"][a + 1:b] if leg[0] == "walk")
        out.append((r["legs"][b][3] - (r["legs"][a][5] + walk), r["legs"][a][1], r["legs"][b][1]))
    return out


def main():
    stops = pd.read_csv("data/stops_all.csv").drop_duplicates("stop_id").set_index("stop_id")
    nets = {"today": Network.today("data/gtfs_eilat/", stops),
            "plan": Network.from_zip("exports/gtfs_eilat_proposal.zip", "weekday_winter", stops)}
    m = O.Problem("full").m
    pts = m.pts
    homes = {}
    for a, g in pts.iloc[m.homes].groupby("area"):
        c = g[["lat", "lon"]].mean()
        homes[int(a)] = (g.index[np.argmin((g.lat - c.lat) ** 2 + (g.lon - c.lon) ** 2)], float(g["pop"].sum()))
    att = Dm.ATTRACTORS
    out = {}
    for name, net in nets.items():
        w_all = w_tr = 0.0; W = []; pairs = {}
        for _, (h, popw) in homes.items():
            o = (float(pts.lat[h]), float(pts.lon[h]))
            for i in range(len(att)):
                d = (float(att.lat[i]), float(att.lon[i]))
                if walk_min(o[0], o[1], d[0], d[1]) < 15:
                    continue
                for t0 in range(7 * 60, 21 * 60, 30):
                    x = waits(net, o, d, t0)
                    if x is None:
                        continue
                    w_all += popw
                    if x:
                        w_tr += popw
                        for wt, a, b in x:
                            W.append((wt, popw)); k = f"{a}->{b}"
                            pairs.setdefault(k, []).append(wt)
        ws = np.array([w for w, _ in W]); pw = np.array([p for _, p in W])
        order = np.argsort(ws); cum = np.cumsum(pw[order]) / pw.sum()
        med = float(ws[order][np.searchsorted(cum, 0.5)])
        top = sorted(pairs.items(), key=lambda kv: -len(kv[1]))[:6]
        out[name] = dict(share_with_transfer=round(w_tr / w_all, 3), median_wait=round(med, 1),
                         share_wait_le5=round(float(pw[ws <= 5].sum() / pw.sum()), 3),
                         share_wait_gt15=round(float(pw[ws > 15].sum() / pw.sum()), 3),
                         top_pairs={k: dict(n=len(v), median=round(float(np.median(v)), 1)) for k, v in top})
        print(name, out[name], flush=True)
    json.dump(out, open("data/transfer_sync.json", "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
