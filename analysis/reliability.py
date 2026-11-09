"""Reliability from SIRI: how late trips start, and how irregular the gaps between buses are.

Gaps: for each line and direction, the bus's passage at a stop half-way along the route (the report closest to
the stop within 120 m, per ride). Gaps between consecutive buses per day; gaps more than 3 x the scheduled
headway are treated as missing data. A passenger arriving at random waits E[H^2] / (2 E[H]) = (h/2)(1 + CV^2),
so (1 + CV^2) is the waiting-time multiplier for irregular service.

Output: data/reliability.csv (line, direction, period: mean gap, CV, wait multiplier), printed summary.
"""
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

DAYS = ["20251207", "20251209", "20251210", "20251211", "20260215", "20260217", "20260218"]
P = {"06-09": (6, 9), "09-12": (9, 12), "12-15": (12, 15), "15-19": (15, 19), "19-24": (19, 24)}
MX, MY = 111_320 * np.cos(np.radians(29.55)), 110_850


def main():
    r = pd.read_csv("data/raw/gtfs_20261107/routes.txt", encoding="utf-8-sig")
    names = dict(zip(r.route_id, r.route_short_name.astype(str), strict=True))
    st = pd.read_csv("data/gtfs_eilat/stop_times.csv").sort_values(["trip_id", "stop_sequence"])
    tr = pd.read_csv("data/gtfs_eilat/trips.csv").merge(pd.read_csv("data/gtfs_eilat/routes.csv")[["route_id", "route_short_name"]], on="route_id")
    stops = pd.read_csv("data/gtfs_eilat/stops.csv").set_index("stop_id")
    # mid stop of the main pattern per line/direction
    mid = {}
    for (ln, d), t in tr.groupby([tr.route_short_name.astype(str), "direction_id"]):
        seq = st[st.trip_id == t.trip_id.iloc[0]].stop_id.values
        mid[(ln, d)] = seq[len(seq) // 2]
    rows, late = [], []
    for day in DAYS:
        x = pd.read_parquet(f"data/siri/{day}.parquet")
        x["line"] = x.siri_route__line_ref.map(names)
        x = x[x.line.isin({ln for ln, _ in mid})]
        # direction from the GTFS route: the same line_ref is one direction
        dmap = dict(zip(tr.route_id, tr.direction_id, strict=False))
        x["dir"] = x.siri_route__line_ref.map(dmap)
        sched = pd.to_datetime(x.siri_ride__scheduled_start_time, utc=True, format="ISO8601")
        g = x.assign(sched=sched).groupby("siri_ride__id")
        first = g.recorded_at_time.min(); s0 = g.sched.first(); ln = g.line.first()
        late.append(pd.DataFrame({"line": ln, "delay_min": (first - s0).dt.total_seconds() / 60}))
        for (line, d), grp in x.groupby(["line", "dir"]):
            if (line, d) not in mid:
                continue
            s = stops.loc[mid[(line, d)]]
            tree = cKDTree(np.c_[grp.lon * MX, grp.lat * MY])
            dist, _ = tree.query([s.stop_lon * MX, s.stop_lat * MY], k=1)
            grp = grp.assign(dm=np.hypot((grp.lon - s.stop_lon) * MX, (grp.lat - s.stop_lat) * MY))
            near = grp[grp.dm < 120].sort_values("dm").drop_duplicates("siri_ride__id").sort_values("recorded_at_time")
            if len(near) < 4:
                continue
            t = near.recorded_at_time.dt.tz_convert("Asia/Jerusalem")
            gaps = t.diff().dt.total_seconds().values[1:] / 60
            hours = t.dt.hour.values[1:]
            for gap, h in zip(gaps, hours, strict=True):
                per = next((k for k, (a, b) in P.items() if a <= h < b), None)
                if per:
                    rows.append(dict(day=day, line=line, dir=d, period=per, gap=gap))
    G = pd.DataFrame(rows)
    # scheduled headway per line/dir/period from GTFS, to drop gaps from missing data
    first_dep = st.groupby("trip_id").dep.min().rename("t0").to_frame().join(tr.set_index("trip_id")[["route_short_name", "direction_id"]])
    first_dep["period"] = (first_dep.t0 // 3600).map(lambda h: next((k for k, (a, b) in P.items() if a <= h < b), None))
    n = first_dep.groupby([first_dep.route_short_name.astype(str), "direction_id", "period"]).size()
    hw = {(a, b, c): (P[c][1] - P[c][0]) * 60 / v for (a, b, c), v in n.items()}
    G["sched"] = [hw.get((a, b, c), np.nan) for a, b, c in zip(G.line, G.dir, G.period, strict=True)]
    G = G[(G.gap > 0.5) & (G.gap <= 3 * G.sched)]
    out = G.groupby(["line", "dir", "period"]).agg(n=("gap", "size"), mean_gap=("gap", "mean"), sd=("gap", "std"), sched=("sched", "first"))
    out["cv"] = out.sd / out.mean_gap
    out["wait_multiplier"] = 1 + out.cv ** 2
    out = out[out.n >= 10]
    out.round(3).to_csv("data/reliability.csv")
    L = pd.concat(late)
    print("trip start vs schedule (min): median %.1f, share > 5 min late %.0f%%, share > 10 min late %.0f%%" %
          (L.delay_min.median(), (L.delay_min > 5).mean() * 100, (L.delay_min > 10).mean() * 100))
    print(out.groupby("line").agg(cv=("cv", "median"), mult=("wait_multiplier", "median"), n=("n", "sum")).round(2).to_string())
    w = (out.wait_multiplier * out.n).sum() / out.n.sum()
    print(f"\ncity-wide waiting multiplier (gap-weighted): {w:.2f}  median CV {out.cv.median():.2f}")


if __name__ == "__main__":
    main()
