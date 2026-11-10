"""Realism checks on the recommended package (option 2, evening to 23:00, 4 hotel shift-change trips), each
against today's network under the same rules:

1. Recovery time:
   - SIRI shows trips run late (median +3.5 min mid-route, 41% over 5 min), so a fixed 5-min terminal
     layover is thin;
   - buses, bus-hours and drivers are recomputed with layover = max(5 min, 10% / 15% of the run).
2. Transfers: the share of bus trips that need a transfer, and of those that change between two lines that
   each run every 30 min or less often (a missed connection costs half an hour or more).
   - basis: winter weekday, every home point x key place x period, weighted by the point's residents.
3. Passed and dropped stops vs older residents:
   - which areas they are in, and those areas' share of residents 65+ (CBS);
   - how far the nearest stop that is still served is.
4. Bus throughput at stops: buses an hour calling at the busiest stops at the midday and afternoon peaks.
   A kerbside stop with one berth handles roughly 30-40 buses an hour at 30-60 s dwell.
5. Holiday peak (Passover, Sukkot): hotels full (occupancy 1.0, 2.6 guests a room for families), schools
   out, hot. The spring/autumn timetable runs; the busiest buses are re-checked as in scripts/capacity.py.

Usage: PYTHONPATH=.:scripts python3 scripts/realism.py   Output: data/realism.json
"""
import json
import math

import geopandas as gpd
import numpy as np
import pandas as pd

import blocking as BL
import evening as EV
import journeys as JR
import optimize as O
import shift_trips as SHT
import shifts as SH
from eilat import demand as Dm
from eilat import params as P

REC = "full_peak-3_warm"   # the recommended plan


def season_trips(tag, se, st, hotels):
    if tag == "today":
        t = BL.option_trips("today", se, st)
        return t[~t.line.isin(BL.SCHOOL)] if se == "summer" else t
    t = BL.option_trips(tag, se, st, 23)
    x = SHT.shift_trips(BL.option_net(tag, se), hotels)
    return pd.concat([t, x[x.o.isin(st.index) & x.d.isin(st.index)]], ignore_index=True)


def recovery(st, hotels):
    out = {}
    for rec in (0.0, 0.10, 0.15):
        for tag in ("today", "keep", REC):
            rows = []
            for se in P.SEASONS:
                B, _, blocks = BL.block(season_trips(tag, se, st, hotels), st, recovery=rec)
                for sc, dmax in SH.SCENARIOS.items():
                    r = SH.staff([p for b in blocks for p in SH.pieces(b, dmax)])
                    rows.append(dict(season=se, scenario=sc, buses=len(blocks), bus_hours=B.hours_out.sum(), **r))
            y = EV.yearly(pd.DataFrame(rows))
            out[f"{tag}@{rec}"] = dict(buses=int(y["standard"]["buses"]), headcount_overtime=int(y["overtime"]["headcount"]),
                                       bus_hours_year=round(y["standard"]["bus_hours"]))
            print("recovery", rec, tag, out[f"{tag}@{rec}"], flush=True)
    return out


def transfers():
    probs = {"full": O.Problem("full")}
    m = probs["full"].m
    names = {i: n for i, n in enumerate(m.ev.stops.stop_name)}
    att = list(Dm.ATTRACTORS.name)
    nets = {"today": probs["full"].base, "keep": EV.thinned(BL.option_net("keep", "winter"), 23),
            REC: EV.thinned(BL.option_net(REC, "winter"), 23)}
    out = {}
    for t, net in nets.items():
        w_all = w_tr = w_rare = 0.0
        for q in P.PERIODS:
            res = m.ev.run(net, q, w_walk=P.W_WALK, sources=m.homes)
            for a_i, name in enumerate(att):
                if JR.WHEN.get(name) and q not in JR.WHEN[name]:
                    continue
                j = int(m.att[a_i])
                for i, h in enumerate(m.homes):
                    it = JR.itinerary(m, res, i, j, net, names, P.W_WALK)
                    if it["mode"] != "bus":
                        continue
                    w = float(m.pts["pop"].values[h])
                    w_all += w
                    if it["transfers"] > 0:
                        w_tr += w
                        rides = [s for s in it["steps"] if s["kind"] == "ride"]
                        if all(2 * s["wait"] >= 30 for s in rides):
                            w_rare += w
        out[t] = dict(share_with_transfer=round(w_tr / w_all, 3), share_rare_connection=round(w_rare / w_all, 3))
        print("transfers", t, out[t], flush=True)
    return out


def elderly():
    a = gpd.read_file("data/areas.geojson")
    s = pd.read_csv(f"data/stops_{REC}.csv")
    allst = pd.read_csv("data/stops_all.csv").set_index("stop_id")
    s = s.join(allst[["stop_lat", "stop_lon"]], on="stop_id")
    g = gpd.GeoDataFrame(s, geometry=gpd.points_from_xy(s.stop_lon, s.stop_lat), crs=a.crs)
    g = gpd.sjoin(g, a[["stat11", "use", "age65_pcnt", "geometry"]], how="left", predicate="within")
    out = {}
    for kind, d in g.groupby("kind"):
        old = d[d.age65_pcnt >= 15]
        out[kind] = dict(stops=len(d), boardings_today=int(d.use_today.sum()), in_areas_65plus_15pct=len(old),
                         boardings_in_those=int(old.use_today.sum()),
                         nearest_served_m_median=int(d.nearest_m.median()), nearest_served_m_max=int(d.nearest_m.max()),
                         over_300m=int((d.nearest_m > 300).sum()))
    worst = g[g.age65_pcnt >= 15].sort_values("nearest_m", ascending=False).head(5)
    out["farthest_in_older_areas"] = [dict(stop=r.name, area=int(r.stat11), age65=float(r.age65_pcnt), kind=r.kind,
                                           nearest=r.nearest_served, m=int(r.nearest_m), boardings_today=int(r.use_today))
                                      for r in worst.itertuples()]
    print("elderly", out, flush=True)
    return out


def throughput():
    prob = O.Problem("full")
    names = dict(zip(prob.sg.stops.stop_id, prob.sg.stops.stop_name, strict=True))
    out = {}
    for t, net in (("today", prob.base), (REC, BL.option_net(REC, "winter"))):
        for q in ("12-15", "15-19"):
            per = {}
            for p in net:
                h = p.headway.get(q, math.inf)
                if not math.isfinite(h):
                    continue
                for s in set(p.stops) - p.skip:
                    per[s] = per.get(s, 0) + 60 / h
            top = sorted(per.items(), key=lambda kv: -kv[1])[:4]
            out[f"{t} {q}"] = [dict(stop=names.get(s, s), buses_per_hour=round(v, 1)) for s, v in top]
        print("throughput", t, out[f"{t} 12-15"][:2], flush=True)
    return out


def holiday():
    P.SEASONS["holiday"] = dict(months=0, school=False, hot=True)
    P.OCCUPANCY["holiday"] = 1.0
    g0 = P.GUESTS_PER_ROOM
    P.GUESTS_PER_ROOM = 2.6
    out = {}
    try:
        for t in ("today", REC):
            prob = O.Problem("full")
            net = prob.base if t == "today" else EV.thinned(BL.option_net(REC, "spring_autumn"), 23)
            r = prob.m.run(net, "holiday", K=prob.cal["K"], track=True, **prob.kw)
            worst = []
            for q, (a, b) in P.PERIODS.items():
                for k, pt in enumerate(net):
                    h = pt.headway.get(q, math.inf)
                    if math.isfinite(h):
                        per_bus = r["load"][q][k].max() / (b - a) / (60 / h) * 1.5
                        worst.append((per_bus, pt.name, q))
            worst.sort(reverse=True)
            out[t] = [dict(per_bus_busiest_hour=round(v, 1), line=n, period=q) for v, n, q in worst[:3]]
            print("holiday", t, out[t], flush=True)
    finally:
        P.GUESTS_PER_ROOM = g0
        del P.SEASONS["holiday"], P.OCCUPANCY["holiday"]
    return out


def main():
    st = pd.read_csv("data/stops_all.csv").set_index("stop_id")
    hotels = SHT.hotel_stops()
    out = dict(elderly=elderly(), throughput=throughput(), holiday=holiday(), transfers=transfers(),
               recovery=recovery(st, hotels))
    json.dump(out, open("data/realism.json", "w"), ensure_ascii=False, indent=1, default=lambda x: x.item() if hasattr(x, "item") else str(x))


if __name__ == "__main__":
    _ = np
    main()
