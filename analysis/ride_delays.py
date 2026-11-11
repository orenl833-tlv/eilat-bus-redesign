"""How late and how slow is each real bus trip? From SIRI vehicle positions (about one a minute).

The reported distance along the route is unreliable (jumps of kilometres in a minute), so positions are used,
as in analysis/segment_times.py. Per ride (urban lines; the line's direction from its GTFS route):
- departure delay d0 = how much later than a typical ride of that hour the bus passed the first of the route's
  first 3 stops it was matched at: passing time - (scheduled start + the typical minutes from the first stop
  to it at that hour). (Buses often wait away from the first stop's mapped point, or start reporting once
  moving, so the first stop itself is often not matched.)
- run ratio = the actual time between the first and the last stop the track passes (stops matched within
  60 m, in route order and within a time window from the schedule) / the typical time for the same stretch at that hour (the sum of the segments'
  measured times at the hour the bus passes them, eilat/speeds.py). 1.0 = a typical ride for that hour,
  1.3 = 30% slower.
Rides matched on less than half of the route are left out.

Usage: python3 analysis/ride_delays.py   Output: data/ride_delays.csv (line, direction, period, hour, d0, ratio)
"""
import glob
import sys

import numpy as np
import pandas as pd

sys.path[:0] = ["analysis", "."]
from segment_times import local_xy, match_ride, route_tables  # noqa: E402

from eilat.speeds import Speeds  # noqa: E402

P = {"06-09": (6, 9), "09-12": (9, 12), "12-15": (12, 15), "15-19": (15, 19), "19-24": (19, 24)}
URBAN = {"1", "1א", "2", "3", "4", "5", "5א", "6", "6א", "15", "16"}


def main():
    sp = Speeds()
    tr = pd.read_csv("data/gtfs_eilat/trips.csv")
    ro = pd.read_csv("data/gtfs_eilat/routes.csv")
    info = tr.groupby("route_id").direction_id.first().to_frame().join(ro.set_index("route_id").route_short_name.astype(str))
    info = info[info.route_short_name.isin(URBAN)]
    st = pd.read_csv("data/gtfs_eilat/stop_times.csv").sort_values(["trip_id", "stop_sequence"]).merge(tr[["trip_id", "route_id"]], on="trip_id")
    main_seq, cum = route_tables(st)
    stops = pd.read_csv("data/stops_all.csv").drop_duplicates("stop_id").set_index("stop_id")
    sx, sy = local_xy(stops.stop_lat, stops.stop_lon)
    pos = dict(zip(stops.index, zip(sx, sy, strict=True), strict=True))
    rows = []
    for f in sorted(glob.glob("data/siri/*.parquet")):
        x = pd.read_parquet(f, columns=["recorded_at_time", "lat", "lon", "siri_route__line_ref", "siri_ride__id",
                                        "siri_ride__scheduled_start_time"])
        x = x[x.siri_route__line_ref.isin(info.index)].drop_duplicates(["siri_ride__id", "recorded_at_time"])
        for _, g in x.sort_values("recorded_at_time").groupby("siri_ride__id"):
            rid = g.siri_route__line_ref.iloc[0]
            if len(g) < 5 or len(main_seq[rid]) < 4:
                continue
            seq, sch, tp, first = match_ride(g, main_seq[rid], cum[rid], pos)
            s0 = pd.to_datetime(g.siri_ride__scheduled_start_time.iloc[0], utc=True, format="ISO8601")
            start = s0.tz_convert("Asia/Jerusalem")
            c0 = start.hour * 60 + start.minute

            def typical(i, j, clock):
                """Typical minutes from stop i to stop j leaving i at clock (minutes after midnight)."""
                m = 0.0
                for k in range(i, j):
                    v = sp.minutes(seq[k], seq[k + 1], clock + m)
                    if v is None:
                        v = (sch[k + 1] - sch[k]) * sp.city_factor(clock + m)
                    m += v
                return m

            ok = np.where(np.isfinite(tp))[0]
            first3 = ok[ok < 3]
            if len(ok) < 2 or not len(first3) or ok[-1] - ok[0] < len(seq) / 2:
                continue
            k0 = first3[0]
            passed = first + pd.Timedelta(seconds=tp[k0])
            d0 = (passed - s0).total_seconds() / 60 - typical(0, k0, c0)
            i, j = ok[0], ok[-1]
            actual = (tp[j] - tp[i]) / 60
            clock = (first + pd.Timedelta(seconds=tp[i])).tz_convert("Asia/Jerusalem")
            typ = typical(i, j, clock.hour * 60 + clock.minute)
            if not np.isfinite(typ) or typ <= 0:
                continue
            ratio = actual / typ
            if not (0.5 <= ratio <= 2.5 and -5 <= d0 <= 40):
                continue
            h = start.hour
            per = next((k for k, (a, b) in P.items() if a <= h < b), None)
            if per:
                rows.append(dict(line=info.route_short_name[rid], direction=int(info.direction_id[rid]), period=per, hour=h,
                                 d0=round(d0, 2), ratio=round(ratio, 3)))
        print(f, len(rows), flush=True)
    D = pd.DataFrame(rows)
    D.to_csv("data/ride_delays.csv", index=False)
    print(len(D), "rides")
    print("departure delay (min): median %.1f, P90 %.1f; run ratio: median %.2f, P10-P90 %.2f-%.2f" % (
        D.d0.median(), D.d0.quantile(.9), D.ratio.median(), D.ratio.quantile(.1), D.ratio.quantile(.9)))
    q90 = lambda v: v.quantile(.9)  # noqa: E731
    print(D.groupby(["line", "direction"]).agg(n=("d0", "size"), d0=("d0", "median"), d0_p90=("d0", q90),
                                               ratio=("ratio", "median"), ratio_p90=("ratio", q90)).round(2).to_string())
    print(D.groupby("hour").agg(n=("d0", "size"), d0=("d0", "median"), d0_p90=("d0", q90),
                                ratio_p90=("ratio", q90)).round(2).to_string())


if __name__ == "__main__":
    main()
