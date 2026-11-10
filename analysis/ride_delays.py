"""How late and how slow is each real bus trip? From SIRI vehicle positions (one report a minute, with the
distance travelled since the trip's start).

Per ride (urban lines):
- departure delay d0 = the first report more than 200 m along the route - the scheduled start;
- run ratio = actual time from that point to 97% of the route's length / the scheduled time for the same stretch
  (the scheduled run of the route, median over its GTFS trips, scaled by the share of the route covered).
The ratio is later used relative to its line/period mean, which the timetables already contain (the measured
run-time factor), so the sampled deviation has a mean of zero; d0 is used as measured.

Usage: python3 analysis/ride_delays.py   Output: data/ride_delays.csv (line, period, hour of the scheduled start, d0, ratio)
"""
import glob

import numpy as np
import pandas as pd

P = {"06-09": (6, 9), "09-12": (9, 12), "12-15": (12, 15), "15-19": (15, 19), "19-24": (19, 24)}
URBAN = {"1", "2", "3", "4", "5", "5א", "6", "6א", "15", "16"}


def main():
    r = pd.read_csv("data/raw/gtfs_20261107/routes.txt", encoding="utf-8-sig")
    names = dict(zip(r.route_id, r.route_short_name.astype(str), strict=True))
    st = pd.read_csv("data/gtfs_eilat/stop_times.csv")
    tr = pd.read_csv("data/gtfs_eilat/trips.csv")
    dur = st.groupby("trip_id").agg(t0=("dep", "min"), t1=("arr", "max"), m=("shape_dist_traveled", "max"))
    dur = dur.join(tr.set_index("trip_id").route_id)
    sched = dur.assign(min=(dur.t1 - dur.t0) / 60).groupby("route_id").agg(sched_min=("min", "median"), metres=("m", "median"))
    rows = []
    for f in sorted(glob.glob("data/siri/*.parquet")):
        x = pd.read_parquet(f)
        x = x[x.siri_route__line_ref.isin(sched.index)]
        x["line"] = x.siri_route__line_ref.map(names)
        x = x[x.line.isin(URBAN)]
        x["t"] = x.recorded_at_time
        x["s0"] = pd.to_datetime(x.siri_ride__scheduled_start_time, utc=True, format="ISO8601")
        for rid, g in x.groupby("siri_ride__id"):
            g = g.sort_values("t")
            ref = sched.loc[g.siri_route__line_ref.iloc[0]]
            total = ref.metres if np.isfinite(ref.metres) and ref.metres > 0 else g.distance_from_journey_start.max()
            moved = g[g.distance_from_journey_start > 200]
            near_end = g[g.distance_from_journey_start >= 0.97 * total]
            if moved.empty or near_end.empty or total < 3000:
                continue
            t_dep, t_end = moved.t.iloc[0], near_end.t.iloc[0]
            run = (t_end - t_dep).total_seconds() / 60
            d0 = (t_dep - g.s0.iloc[0]).total_seconds() / 60
            share = (0.97 * total - 200) / total
            ratio = run / (ref.sched_min * share)
            if not (0.6 <= ratio <= 2.5 and -5 <= d0 <= 40):
                continue
            h = g.s0.iloc[0].tz_convert("Asia/Jerusalem").hour
            per = next((k for k, (a, b) in P.items() if a <= h < b), None)
            if per:
                rows.append(dict(line=g.line.iloc[0].replace("א", ""), period=per, hour=h, d0=round(d0, 2), ratio=round(ratio, 3)))
    D = pd.DataFrame(rows)
    D.to_csv("data/ride_delays.csv", index=False)
    print(len(D), "rides")
    print("departure delay (min): median %.1f, P90 %.1f; run ratio: median %.2f, P10-P90 %.2f-%.2f" % (
        D.d0.median(), D.d0.quantile(.9), D.ratio.median(), D.ratio.quantile(.1), D.ratio.quantile(.9)))
    print(D.groupby("hour").agg(n=("d0", "size"), d0=("d0", "median"), d0_p90=("d0", lambda v: v.quantile(.9)),
                                ratio=("ratio", "median")).round(2).to_string())
    print(D.groupby("line").agg(n=("d0", "size"), d0=("d0", "median"), ratio=("ratio", "median")).round(2).to_string())


if __name__ == "__main__":
    main()
