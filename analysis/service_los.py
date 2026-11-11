"""Is each residential area well served, on an absolute yardstick (not compared with today)?

Targets from the Fort Collins public transportation level of service standard ("remainder of service area"),
as reproduced in ODOT's "Public Transportation Level of Service" (Oregon Public Transportation Plan, Table 4),
which follows the TCQSM's availability / comfort concepts:
- access: a stop within 1/4 mile (400 m) walk;
- hours of weekday service >= 16 (first to last departure at the resident's stops);
- weekday frequency: one line at a nearby stop every 20 min or better, 07:00-19:00;
- travel time factor <= 2.0 x the car (here door to door, both: bus with walking, waiting and real delays on
  the timetable; car = road distance (straight x DETOUR) at CAR_KMH + CAR_EXTRA_MIN to park, an assumption);
- (peak load factor <= 1.2 is not per area: left out.)
Each home point gets the number of targets met (0 without a stop in 400 m); an area's class is that of its
median resident (by population): 3 = good (green), 2 = fair (amber), 0-1 = poor (red).

Usage: PYTHONPATH=.:scripts:analysis python3 analysis/service_los.py   Output: data/service_los.json
"""
import json
import random

import numpy as np
import pandas as pd

import optimize as O
from eilat import demand as Dm
from eilat import params as P
from eilat.evaluate import walk_min
from eilat.speeds import Speeds
from eilat.timetable import DelaySampler, Network

ACCESS_M, HOURS_MIN, HEADWAY_MAX, TTF_MAX = 400, 16, 20, 2.0
CAR_KMH, CAR_EXTRA_MIN = 30.0, 3.0
KEYS = ["City hall / centre", "Old central station (Star Eilat)", "Hotels, North Beach", "Big centre", "Yoseftal hospital", "Coral Beach"]
SEEDS = range(1300, 1303)


def car_min(o, d):
    km = walk_min(o[0], o[1], d[0], d[1]) * P.WALK_KMH / 60      # walking distance (with detour), km
    return km / CAR_KMH * 60 + CAR_EXTRA_MIN


def stop_stats(net):
    """Per stop: first and last departure (min), and the best single pattern's departures 07-19 per hour."""
    first, last, best = {}, {}, {}
    per = {}
    for tid, (s, t) in net.trips.items():
        key = (net.line.get(tid, ""), int(s[0]), int(s[-1]))
        for sid, tt in zip(s[:-1], t[:-1], strict=True):
            sid = int(sid)
            first[sid] = min(first.get(sid, 1e9), tt); last[sid] = max(last.get(sid, -1), tt)
            if 7 * 60 <= tt < 19 * 60:
                per[(sid, key)] = per.get((sid, key), 0) + 1
    for (sid, _), n in per.items():
        best[sid] = max(best.get(sid, 0), n / 12)
    return first, last, best


def main():
    stops = pd.read_csv("data/stops_all.csv").drop_duplicates("stop_id").set_index("stop_id")
    sp = Speeds()
    today = Network.today("data/gtfs_eilat/", stops, sp)
    plan = Network.from_zip("exports/gtfs_eilat_proposal.zip", "weekday_winter", stops, today.foot)
    m = O.Problem("full").m
    homes = m.pts.iloc[m.homes]
    att = Dm.ATTRACTORS
    dests = [(float(att.lat[list(att.name).index(k)]), float(att.lon[list(att.name).index(k)])) for k in KEYS]
    sampler = DelaySampler()
    out = {"targets": dict(access_m=ACCESS_M, hours=HOURS_MIN, headway=HEADWAY_MAX, ttf=TTF_MAX, car_kmh=CAR_KMH,
                           car_extra_min=CAR_EXTRA_MIN, source="Fort Collins PTLOS targets via ODOT Public Transportation Level of Service")}
    for name, net in (("today", today), ("net_H", plan)):
        first, last, best = stop_stats(net)
        reals = [net.realize(sampler, s) for s in SEEDS]
        rows = []
        for idx, r in homes.iterrows():
            o = (float(r.lat), float(r.lon))
            dist_m = walk_min(o[0], o[1], stops.stop_lat.values, stops.stop_lon.values) * P.WALK_KMH * 1000 / 60
            near = [sid for sid, dm in zip(stops.index, dist_m, strict=True) if dm <= ACCESS_M and sid in first]
            if not near:
                rows.append(dict(area=int(r.area), pop=float(r["pop"]), access=0, hours=0.0, per_hour=0.0, ttf=np.nan, met=0))
                continue
            hours = (max(last[s] for s in near) - min(first[s] for s in near)) / 60
            per_hour = max(best.get(s, 0) for s in near)
            rng = random.Random(f"los|{idx}")
            ratios = []
            for _ in range(8):
                t0 = 7 * 60 + rng.random() * 12 * 60
                for real in reals:
                    arr = real.arrivals(o[0], o[1], dests, t0, 2.0)
                    for d, a in zip(dests, arr, strict=True):
                        wd = float(walk_min(o[0], o[1], d[0], d[1]))
                        bus = wd if not np.isfinite(a) else min(a - t0, wd)
                        ratios.append(bus / car_min(o, d))
            ttf = float(np.mean(ratios))
            met = int(hours >= HOURS_MIN) + int(per_hour >= 60 / HEADWAY_MAX) + int(ttf <= TTF_MAX)
            rows.append(dict(area=int(r.area), pop=float(r["pop"]), access=1, hours=round(hours, 1), per_hour=round(per_hour, 1),
                             ttf=round(ttf, 2), met=met))
        D = pd.DataFrame(rows)
        res = {}
        for a, g in D.groupby("area"):
            g = g.sort_values("met"); c = g["pop"].cumsum() / g["pop"].sum()
            med = g[c >= 0.5].iloc[0]
            share = lambda mask: round(float(g["pop"][mask].sum() / g["pop"].sum()), 2)  # noqa: E731
            res[str(a)] = dict(met=int(med.met), cls="good" if med.met == 3 else "fair" if med.met == 2 else "poor",
                               access=share(g.access == 1), hours=share(g.hours >= HOURS_MIN),
                               freq=share(g.per_hour >= 60 / HEADWAY_MAX), ttf=share(g.ttf <= TTF_MAX),
                               ttf_median=round(float(g.ttf.median()), 2) if g.ttf.notna().any() else None)
        out[name] = res
        cls = pd.Series({a: v["cls"] for a, v in res.items()})
        print(name, cls.value_counts().to_dict(), flush=True)
    json.dump(out, open("data/service_los.json", "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
