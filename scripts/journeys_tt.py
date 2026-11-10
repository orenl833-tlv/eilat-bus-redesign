"""Example trips on the real timetables: today's GTFS (run times as measured) and each option's exported GTFS
(winter weekday, evening to 23:00 with the shift-change trips).

For every residential area (its point nearest the area's centre) x key place x time of day, the trip is planned
leaving home at four times 15 minutes apart (07:00-07:45, 10:00-10:45, 13:00-13:45, 17:00-17:45,
21:00-21:45), as a trip-planner app would. A trip's time is door to door; when no bus gets there (or walking is
quicker) the walk counts.

The examples are picked on option 2 vs today (mean over the four departures), among trips that a bus serves at
every departure both today and in option 2, with today's mean wait at most 30 min (no "today you can only walk"
or "wait an hour for the first bus" cases):
- the three biggest gains;
- the three biggest losses;
- two everyday trips (to the hospital and the campus).

Usage: PYTHONPATH=.:scripts python3 scripts/journeys_tt.py   Output: data/journeys_tt.json
"""
import json

import numpy as np
import pandas as pd

import journeys as JR
import optimize as O
from eilat import demand as Dm
from eilat.evaluate import walk_min
from eilat.timetable import Network
from export_page import public_name

NETS = {"today": "היום", "keep": "אפשרות 1", "full_warm": "אפשרות 2", "full_peak-3_warm": "אפשרות 3"}
LEAVE = {"06-09": 7 * 60, "09-12": 10 * 60, "12-15": 13 * 60, "15-19": 17 * 60, "19-24": 21 * 60}
MAX_WAIT_TODAY = 30
WHEN_HE = {"06-09": "בבוקר", "09-12": "באמצע הבוקר", "12-15": "בצהריים", "15-19": "אחר הצהריים", "19-24": "בערב"}


def hhmm(m):
    m = int(round(m)); return f"{m // 60:02d}:{m % 60:02d}"


def trip(net, o, d, t0, names, walk_direct):
    r = net.plan(o[0], o[1], d[0], d[1], t0)
    if r is None or r["arrive"] - t0 >= walk_direct:
        return dict(mode="walk", total=round(walk_direct), walk=round(walk_direct), wait=0, ride=0, transfers=0, steps=[], nobus=r is None)
    walk = ride = 0.0; steps = []; rides = 0
    for leg in r["legs"]:
        if leg[0] == "walk":
            walk += leg[1]
            steps.append(dict(kind="walk", min=round(leg[1], 1), to=names.get(leg[2], "היעד") if leg[2] else "היעד"))
        else:
            _, line, a, dep, b, arr, n = leg
            disp, note = public_name(line)
            ride += arr - dep; rides += 1
            steps.append(dict(kind="ride", lines=[dict(line=disp, note=note)], board=names.get(a, ""), alight=names.get(b, ""),
                              dep=hhmm(dep), arr=hhmm(arr), ride=round(arr - dep, 1), stops=n))
    total = r["arrive"] - t0
    return dict(mode="bus", total=round(total), walk=round(walk), ride=round(ride), wait=round(total - walk - ride),
                transfers=max(rides - 1, 0), steps=steps, leave=hhmm(t0), arrive=hhmm(r["arrive"]), nobus=False)


def main():
    stops = pd.read_csv("data/stops_all.csv").drop_duplicates("stop_id").set_index("stop_id")
    names = stops.stop_name.to_dict()
    nets = {"today": Network.today("data/gtfs_eilat/", stops)}
    for t in ["keep", "full_warm", "full_peak-3_warm"]:
        nets[t] = Network.from_zip(f"exports/gtfs_{t}.zip", "weekday_winter", stops)
    m = O.Problem("full").m
    pts = m.pts
    att = list(Dm.ATTRACTORS.name)
    # one home point per area: the one nearest the area's centre
    homes = {}
    for a, g in pts.iloc[m.homes].groupby("area"):
        c = g[["lat", "lon"]].mean()
        homes[int(a)] = g.index[np.argmin((g.lat - c.lat) ** 2 + (g.lon - c.lon) ** 2)]
    cand = []
    for q, t0 in LEAVE.items():
        for a_i, place in enumerate(att):
            if JR.WHEN.get(place) and q not in JR.WHEN[place]:
                continue
            d = (float(Dm.ATTRACTORS.lat[a_i]), float(Dm.ATTRACTORS.lon[a_i]))
            for area, h in homes.items():
                o = (float(pts.lat[h]), float(pts.lon[h]))
                wd = float(walk_min(o[0], o[1], d[0], d[1]))
                if wd < 15:
                    continue
                res = {}
                for t, net in nets.items():
                    runs = [trip(net, o, d, t0 + k * 15, names, wd) for k in range(4)]
                    res[t] = dict(first=runs[0], mean=float(np.mean([r["total"] for r in runs])),
                                  lo=min(r["total"] for r in runs), hi=max(r["total"] for r in runs),
                                  nobus=sum(r["nobus"] or r["mode"] == "walk" for r in runs),
                                  walk=float(np.mean([r["walk"] for r in runs])), wait=float(np.mean([r["wait"] for r in runs])),
                                  ride=float(np.mean([r["ride"] for r in runs])))
                cand.append(dict(area=area, home=int(h), place=place, period=q, res=res,
                                 delta=res["full_warm"]["mean"] - res["today"]["mean"]))
        print(q, len(cand), flush=True)
    # only trips a bus serves today and in option 2 at every departure: no "today you can only walk" cases
    # and no "waiting an hour for the first bus" cases either: today's mean wait at most MAX_WAIT_TODAY
    cand = [c for c in cand if c["res"]["today"]["nobus"] == 0 and c["res"]["full_warm"]["nobus"] == 0
            and c["res"]["today"]["wait"] <= MAX_WAIT_TODAY]
    cand.sort(key=lambda c: c["delta"])

    def pick(pool, n, used):
        out = []
        for c in pool:
            if (c["area"], c["place"]) in used or any(c["place"] == o["place"] for o in out):
                continue
            used.add((c["area"], c["place"])); out.append(c)
            if len(out) == n:
                break
        return out
    used = set()
    best = pick(cand, 3, used)
    worst = pick(list(reversed(cand)), 3, used)
    mid = [c for c in cand if c["place"] in ("Yoseftal hospital", "Eilat campus")]
    typical = pick(sorted(mid, key=lambda c: abs(c["delta"] + 3)), 2, used)
    out = []
    for group, cs in (("best", best), ("worst", worst), ("typical", typical)):
        for c in cs:
            h = c["home"]
            near = names.get(int(stops.index[np.argmin(walk_min(pts.lat[h], pts.lon[h], stops.stop_lat.values, stops.stop_lon.values))]), "")
            opts = {}
            for t, label in NETS.items():
                r = c["res"][t]
                opts[label] = dict(r["first"], total=round(r["mean"]), walk=round(r["walk"]), wait=round(r["wait"]), ride=round(r["ride"]),
                                   lo=r["lo"], hi=r["hi"], nobus=r["nobus"])
            t0 = LEAVE[c["period"]]
            out.append(dict(group=group, area=c["area"], home_stop=near, place=JR.PLACE_HE[c["place"]], period=c["period"],
                            when=f"{WHEN_HE[c['period']]}, יציאה מהבית בין {hhmm(t0)} ל-{hhmm(t0 + 45)}",
                            delta=round(c["delta"]), options=opts))
            print(group, c["area"], c["place"], c["period"], {t: round(c["res"][t]["mean"]) for t in NETS}, flush=True)
    json.dump(out, open("data/journeys_tt.json", "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
