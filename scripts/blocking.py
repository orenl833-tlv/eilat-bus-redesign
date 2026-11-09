"""Timetables and vehicle blocks: how many buses an option really needs, with depot runs and layovers.

1. Departures: today's = the real GTFS trips; an option's = every `headway` minutes in each period, the two
   directions of a line offset by half a headway, run times per period from the network model.
2. Blocks (one bus's day): the minimum number of buses that covers all trips (minimum path cover = trips minus
   a maximum bipartite matching). Trip j can follow trip i on the same bus if i's end + layover (+ an empty run
   between their terminals, straight line x 1.3 at 25 km/h) <= j's start. Lines may share buses.
3. Each bus starts and ends its day at the depot (stop 50286); those empty runs are added.
4. Per option: buses, the most in service at once, bus-hours (first departure to last arrival per bus, incl.
   layovers and depot runs), km per bus a day vs the e-bus range, driver shifts (a shift <= 8.5 h).

Usage: PYTHONPATH=.:scripts python3 scripts/blocking.py   Output: data/blocking.csv
"""
import json
import math

import numpy as np
import pandas as pd
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import maximum_bipartite_matching

import optimize as O
from eilat import params as P
from eilat.evaluate import walk_min

DEPOT = 50286
LAYOVER_MIN = 5.0
DEAD_KMH = 25.0
SHIFT_H = 8.5
DEPOT_GAP = 60   # minutes idle after which a bus returns to the depot
SCHOOL = {"80", "80א", "81", "82"}


def km_between(st, a, b):
    x, y = st.loc[a], st.loc[b]
    return float(walk_min(x.stop_lat, x.stop_lon, y.stop_lat, y.stop_lon)) * P.WALK_KMH / 60  # includes DETOUR


def trips_from_network(net):
    rows = []
    for k, p in enumerate(net):
        off = 0.5 if p.name.endswith("/1") or "/1" in p.name else 0.0
        for q, (a, b) in P.PERIODS.items():
            h = p.headway.get(q, math.inf)
            if not math.isfinite(h):
                continue
            t = a * 60 + off * h
            while t < b * 60:
                run = p.run_min(q)
                rows.append(dict(line=p.line, start=t, end=t + run, o=p.stops[0], d=p.stops[-1],
                                 km=sum(p.seg_min[q]) / max(p.run_min(q), 1e-9) * 0 + np.nan))
                t += h
    return pd.DataFrame(rows)


def trips_today():
    st = pd.read_csv("data/gtfs_eilat/stop_times.csv").sort_values(["trip_id", "stop_sequence"])
    tr = pd.read_csv("data/gtfs_eilat/trips.csv").merge(pd.read_csv("data/gtfs_eilat/routes.csv")[["route_id", "route_short_name"]], on="route_id")
    fac = pd.read_csv("data/runtime_factor.csv", dtype={"line": str})
    g = st.groupby("trip_id").agg(start=("dep", "min"), end=("arr", "max"), o=("stop_id", "first"), d=("stop_id", "last"),
                                  m=("shape_dist_traveled", "max"))
    g = g.join(tr.set_index("trip_id").route_short_name.astype(str).rename("line"))
    g["start"] /= 60; g["end"] /= 60
    per = lambda h: next((k for k, (a, b) in P.PERIODS.items() if a <= h < b), "19-24")  # noqa: E731
    f = []
    for r in g.itertuples():
        m = fac[(fac.line == r.line.replace("א", "")) & (fac.period == per(int(r.start // 60)))].factor
        f.append(float(m.iloc[0]) if len(m) else 1.24)
    g["end"] = g.start + (g.end - g.start) * np.array(f)     # real run times, as measured
    return g.reset_index(drop=True)[["line", "start", "end", "o", "d"]]


def block(trips, st):
    trips = trips.sort_values("start").reset_index(drop=True)
    n = len(trips)
    ends, starts = trips.end.values, trips.start.values
    rows, cols = [], []
    cache = {}
    for i in range(n):
        for j in np.where(starts > ends[i])[0]:
            key = (trips.d[i], trips.o[j])
            if key not in cache:
                cache[key] = 0.0 if key[0] == key[1] else km_between(st, *key) / DEAD_KMH * 60
            if ends[i] + LAYOVER_MIN + cache[key] <= starts[j]:
                rows.append(i); cols.append(j)
    G = csr_matrix((np.ones(len(rows)), (rows, cols)), shape=(n, n))
    match = maximum_bipartite_matching(G, perm_type="column")   # match[i] = j that follows i, or -1
    nxt = {i: int(j) for i, j in enumerate(match) if j >= 0}
    has_prev = set(nxt.values())
    blocks = []
    for i in range(n):
        if i in has_prev:
            continue
        chain = [i]
        while chain[-1] in nxt:
            chain.append(nxt[chain[-1]])
        blocks.append(chain)
    # per bus: span incl. depot runs, km (service km from straight-line estimate of run time at 18 km/h is too
    # rough, so km = run minutes x measured average speed 21 km/h) + empty runs
    out = []
    for ch in blocks:
        t = trips.loc[ch]
        dep_out = km_between(st, DEPOT, t.o.iloc[0]); dep_in = km_between(st, t.d.iloc[-1], DEPOT)
        empty = dep_out + dep_in + sum(km_between(st, a, b) for a, b in zip(t.d.values[:-1], t.o.values[1:], strict=True) if a != b)
        service_km = ((t.end - t.start).sum() / 60) * 21.0
        span = (t.end.max() - t.start.min()) / 60 + (dep_out + dep_in) / DEAD_KMH
        # a bus idle for more than DEPOT_GAP minutes goes back to the depot: those hours aren't paid service
        gaps = t.start.values[1:] - t.end.values[:-1]
        idle = sum(g for g in gaps if g > DEPOT_GAP)
        trips_back = sum(1 for g in gaps if g > DEPOT_GAP)
        extra_km = 0.0
        for a, b, g in zip(t.d.values[:-1], t.o.values[1:], gaps, strict=True):
            if g > DEPOT_GAP:
                extra_km += km_between(st, a, DEPOT) + km_between(st, DEPOT, b)
        hours_out = span - idle / 60 + extra_km / DEAD_KMH
        out.append(dict(trips=len(ch), span_h=span, hours_out=hours_out, km=service_km + empty + extra_km,
                        empty_km=empty + extra_km, depot_returns=trips_back))
    B = pd.DataFrame(out)
    # most buses in service at once (a bus is "out" from its first departure to its last arrival)
    ev = sorted([(trips.loc[ch].start.min(), 1) for ch in blocks] + [(trips.loc[ch].end.max(), -1) for ch in blocks])
    cur = peak = 0
    for _, d in ev:
        cur += d; peak = max(peak, cur)
    return B, peak


def main():
    st = pd.concat([pd.read_csv("data/stops_all.csv")], ignore_index=True).set_index("stop_id")
    rows = []
    sets = [("today", "winter", None)] + [(t, s, t) for t in ["keep", "full_warm", "full_peak-3_warm"] for s in P.SEASONS]
    prob_cache = {}
    for name, season, tag in sets:
        if tag is None:
            trips = trips_today()
        else:
            if tag not in prob_cache:
                prob_cache[tag] = O.Problem("keep" if tag == "keep" else "full", -3 if "peak-3" in tag else 0)
            prob = prob_cache[tag]
            sr = json.load(open(f"data/opt_{tag}_seasonal.json"))[season]
            net = prob.network({k: {q: (h if h is not None else math.inf) for q, h in v.items()} for k, v in sr.items() if k in prob.lines})
            # school lines keep today's real trips
            trips = pd.concat([trips_from_network([p for p in net if p.line not in SCHOOL]),
                               trips_today()[lambda x: x.line.isin(SCHOOL)] if season != "summer" else None], ignore_index=True)
        trips = trips[trips.o.isin(st.index) & trips.d.isin(st.index)]
        B, peak = block(trips, st)
        rows.append(dict(option=name, season=season, trips=len(trips), buses=len(B), out_at_once_max=peak,
                         bus_hours=round(B.hours_out.sum(), 1), bus_span_hours=round(B.span_h.sum(), 1), km_per_bus_max=round(B.km.max()),
                         km_per_bus_mean=round(B.km.mean()),
                         buses_over_250km=int((B.km > 250).sum()), empty_km_share=round(B.empty_km.sum() / B.km.sum(), 3),
                         driver_shifts=int(np.ceil(B.hours_out / SHIFT_H).sum())))
        print(rows[-1], flush=True)
    pd.DataFrame(rows).to_csv("data/blocking.csv", index=False)


if __name__ == "__main__":
    main()
