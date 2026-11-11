"""Example trips on the real timetables: today's GTFS (run times as measured) and each option's exported GTFS
(winter weekday, evening to 23:00 with the shift-change trips).

For every residential area (its point nearest the area's centre) x key place x time of day, the trip is planned
leaving home at four times 15 minutes apart (07:00-07:45, 10:00-10:45, 13:00-13:45, 17:00-17:45,
21:00-21:45), as a trip-planner app would. A trip's time is door to door; when no bus gets there (or walking is
quicker) the walk counts. Today and the plan are timed the same way: every street segment at the GPS-measured
time of that hour and direction (eilat/speeds.py), and 2 minutes needed at a transfer.

Two times per trip: as printed (the timetable's own times) and as it really goes on average: over DRAWS
delay draws (each bus late or slow as a real trip of its line, direction and hour; data/ride_delays.csv),
the rider seeing the actual departures. The examples are picked on the real average.

The examples are picked on the recommended plan (option 3) vs today (mean over the four departures), among trips that a bus serves at
every departure both today and in the plan, with today's mean wait at most 30 min (no "today you can only walk"
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
from eilat.timetable import DelaySampler, Network
from export_page import public_name

PLAN = "full_peak-3_warm"   # the recommended plan
NETS = {"today": "היום", PLAN: "ההצעה"}
LEAVE = {"06-09": 7 * 60, "09-12": 10 * 60, "12-15": 13 * 60, "15-19": 17 * 60, "19-24": 21 * 60}
MAX_WAIT_TODAY = 30
TRANSFER_MIN = 2.0
DRAWS = 10
WHEN_HE = {"06-09": "בבוקר", "09-12": "באמצע הבוקר", "12-15": "בצהריים", "15-19": "אחר הצהריים", "19-24": "בערב"}


def hhmm(m):
    m = int(round(m)); return f"{m // 60:02d}:{m % 60:02d}"


def trip(net, o, d, t0, names, walk_direct):
    r = net.plan(o[0], o[1], d[0], d[1], t0, TRANSFER_MIN)
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
    for t in [PLAN]:
        nets[t] = Network.from_zip("exports/gtfs_eilat_proposal.zip", "weekday_winter", stops, nets["today"].foot)
    sampler = DelaySampler()
    real = {t: [net.realize(sampler, 500 + k) for k in range(DRAWS)] for t, net in nets.items()}
    m = O.Problem("full").m
    pts = m.pts
    att = list(Dm.ATTRACTORS.name)
    # one home point per area: the one nearest the area's centre
    homes = {}
    for a, g in pts.iloc[m.homes].groupby("area"):
        c = g[["lat", "lon"]].mean()
        homes[int(a)] = g.index[np.argmin((g.lat - c.lat) ** 2 + (g.lon - c.lon) ** 2)]
    # real average door to door: one scan per (network, draw, home, leaving time) for all places
    place_xy = [(float(Dm.ATTRACTORS.lat[i]), float(Dm.ATTRACTORS.lon[i])) for i in range(len(att))]
    real_mean = {}
    for t, rs in real.items():
        for area, h in homes.items():
            o = (float(pts.lat[h]), float(pts.lon[h]))
            wds = [float(walk_min(o[0], o[1], d[0], d[1])) for d in place_xy]
            for q, t0 in LEAVE.items():
                acc = np.zeros(len(att))
                for rn in rs:
                    for k in range(4):
                        a = rn.arrivals(o[0], o[1], place_xy, t0 + k * 15, TRANSFER_MIN, max(wds))
                        acc += [wd if not np.isfinite(x) else min(x - (t0 + k * 15), wd) for x, wd in zip(a, wds, strict=True)]
                for i, pl in enumerate(att):
                    real_mean[(t, area, pl, q)] = acc[i] / (4 * len(rs))
        print("real", t, flush=True)
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
                                  ride=float(np.mean([r["ride"] for r in runs])), real=real_mean[(t, area, place, q)])
                cand.append(dict(area=area, home=int(h), place=place, period=q, res=res,
                                 delta=res[PLAN]["real"] - res["today"]["real"],
                                 delta_printed=res[PLAN]["mean"] - res["today"]["mean"]))
        print(q, len(cand), flush=True)
    # only trips a bus serves today and in option 2 at every departure: no "today you can only walk" cases
    # and no "waiting an hour for the first bus" cases either: today's mean wait at most MAX_WAIT_TODAY
    cand = [c for c in cand if c["res"]["today"]["nobus"] == 0 and c["res"][PLAN]["nobus"] == 0
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
                opts[label] = dict(r["first"], total=round(r["real"]), printed=round(r["mean"]), walk=round(r["walk"]),
                                   wait=round(r["wait"]), ride=round(r["ride"]), lo=r["lo"], hi=r["hi"], nobus=r["nobus"])
            t0 = LEAVE[c["period"]]
            out.append(dict(group=group, area=c["area"], home_stop=near, place=JR.PLACE_HE[c["place"]], period=c["period"],
                            when=f"{WHEN_HE[c['period']]}, יציאה מהבית בין {hhmm(t0)} ל-{hhmm(t0 + 45)}",
                            delta=round(c["delta"]), delta_printed=round(c["delta_printed"]), options=opts))
            print(group, c["area"], c["place"], c["period"], {t: (round(c["res"][t]["mean"]), round(c["res"][t]["real"])) for t in NETS},
                  flush=True)
    # all candidate trips: how the plan compares on average, printed and real
    d_real = np.array([c["delta"] for c in cand]); d_pr = np.array([c["delta_printed"] for c in cand])
    t_real = np.array([c["res"]["today"]["real"] for c in cand]); t_pr = np.array([c["res"]["today"]["mean"] for c in cand])
    print(f"all {len(cand)} trips: plan - today, printed {d_pr.mean():+.1f} min ({d_pr.sum() / t_pr.sum():+.1%}), "
          f"real {d_real.mean():+.1f} min ({d_real.sum() / t_real.sum():+.1%}); plan faster in {np.mean(d_real < -0.5):.0%}, "
          f"slower in {np.mean(d_real > 0.5):.0%}")
    json.dump(out, open("data/journeys_tt.json", "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
