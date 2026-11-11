"""Real run time on every street segment between two stops, by hour of day, from the buses' GPS (SIRI).

The reported distance along the route is unreliable (jumps of kilometres within a minute), so each ride is
matched to its stops directly:
- the bus's track is the straight line between consecutive positions (about one a minute);
- the time it passed a stop = the closest point of the track to the stop, if within MATCH_M, searched in route
  order (each stop after the previous one, and within a time window from the schedule), so routes that come
  back along the same street, and loops that end where they start, are handled;
- a segment's time = passing time at the next stop - passing time at this stop (it includes the stop's dwell).
Adjacent matched stops only; a stop that was not matched leaves its two segments out of that ride.

Hour = local hour when the bus passed the first stop of the segment. Output per (from, to, hour): rides and the
median and quartile minutes; and the scheduled minutes (GTFS median) for the same segment.

Usage: python3 analysis/segment_times.py   Output: data/segment_times.csv
"""
import glob

import numpy as np
import pandas as pd

URBAN = {"1", "2", "3", "4", "5", "5א", "6", "6א", "15", "16"}
MATCH_M = 60.0
SLACK, SLACK_MIN, FIRST_MIN = 2.5, 5.0, 15.0   # search window (see passing_times)
MAX_SEG_MIN = 20.0


def local_xy(lat, lon):
    return (np.asarray(lon) - 34.95) * 96_500.0, (np.asarray(lat) - 29.55) * 111_200.0


def passing_times(px, py, pt, sx, sy, sched=None):
    """Time the track (px, py at times pt, seconds) passed each stop (sx, sy) in order; NaN if not matched.
    sched: scheduled minutes from the first stop to each stop; a stop is then searched only up to
    SLACK x its scheduled gap + SLACK_MIN after the last matched stop, so a loop route that comes back to its
    start is not matched to the end of the loop."""
    ax, ay, bx, by = px[:-1], py[:-1], px[1:], py[1:]
    dx, dy = bx - ax, by - ay
    L2 = np.maximum(dx * dx + dy * dy, 1e-6)
    out = np.full(len(sx), np.nan)
    j0 = 0                      # first track segment still allowed (route order)
    last_t, last_k = pt[0], None
    for k in range(len(sx)):
        jn = len(ax)
        if sched is not None and np.isfinite(sched[k]) and (last_k is None or np.isfinite(sched[last_k])):
            gap = sched[k] - (sched[last_k] if last_k is not None else 0.0) + (FIRST_MIN if last_k is None else 0.0)
            jn = max(j0 + 1, int(np.searchsorted(pt[:-1], last_t + 60 * (SLACK * gap + SLACK_MIN), side="right")))
        if j0 >= jn:
            continue
        u = np.clip(((sx[k] - ax[j0:jn]) * dx[j0:jn] + (sy[k] - ay[j0:jn]) * dy[j0:jn]) / L2[j0:jn], 0, 1)
        d = np.hypot(ax[j0:jn] + u * dx[j0:jn] - sx[k], ay[j0:jn] + u * dy[j0:jn] - sy[k])
        hit = np.where(d <= MATCH_M)[0]
        if not len(hit):
            continue
        # the first pass close to the stop: the best point in the first run of close track segments
        run = hit[: np.argmax(np.diff(np.r_[hit, 10**9]) > 1) + 1]
        j = run[np.argmin(d[run])]
        out[k] = pt[j0 + j] + u[j] * (pt[j0 + j + 1] - pt[j0 + j])
        last_t, last_k = out[k], k
        j0 += j
    return out


def route_tables(st):
    """Each route's main stop sequence (its most common one) and the scheduled minutes from its first stop to
    each stop of it (median over the route's trips with that sequence). st: stop_times with route_id."""
    seqs = st.groupby("trip_id").stop_id.apply(tuple)
    route_of = st.groupby("trip_id").route_id.first()
    main, cum = {}, {}
    for rid in route_of.unique():
        sq = seqs[route_of[route_of == rid].index].value_counts().index[0]
        x = st[st.trip_id.isin(seqs[(route_of == rid) & (seqs == sq)].index)]
        x = x.assign(m=(x.dep - x.groupby("trip_id").dep.transform("min")) / 60, k=x.groupby("trip_id").cumcount())
        main[rid], cum[rid] = list(sq), x.groupby("k").m.median().reindex(range(len(sq))).values
    return main, cum


def match_ride(g, seq_all, cum_all, pos):
    """A ride's positions (sorted) -> (stops kept, their scheduled minutes, passing times in seconds from the
    ride's first fix, the first fix's time)."""
    idx = [i for i, s in enumerate(seq_all) if s in pos]
    seq = [seq_all[i] for i in idx]
    px, py = local_xy(g.lat.values, g.lon.values)
    t = g.recorded_at_time
    pt = (t - t.iloc[0]).dt.total_seconds().values
    sx, sy = np.array([pos[s][0] for s in seq]), np.array([pos[s][1] for s in seq])
    return seq, cum_all[idx], passing_times(px, py, pt, sx, sy, cum_all[idx]), t.iloc[0]


def main():
    r = pd.read_csv("data/raw/gtfs_20261107/routes.txt", encoding="utf-8-sig")
    names = dict(zip(r.route_id, r.route_short_name.astype(str), strict=True))
    st = pd.read_csv("data/gtfs_eilat/stop_times.csv").sort_values(["trip_id", "stop_sequence"])
    tr = pd.read_csv("data/gtfs_eilat/trips.csv")
    stops = pd.read_csv("data/stops_all.csv").drop_duplicates("stop_id").set_index("stop_id")
    sx_all, sy_all = local_xy(stops.stop_lat, stops.stop_lon)
    pos = dict(zip(stops.index, zip(sx_all, sy_all, strict=True), strict=True))
    # each route's main stop sequence and the scheduled minutes per segment
    st = st.merge(tr[["trip_id", "route_id"]], on="trip_id")
    main, cum = route_tables(st)
    st["nxt"] = st.groupby("trip_id").stop_id.shift(-1)
    st["sched"] = (st.groupby("trip_id").arr.shift(-1) - st.dep) / 60
    sched = st.dropna(subset=["nxt"]).groupby(["stop_id", "nxt"]).sched.median()
    rows = []
    for f in sorted(glob.glob("data/siri/*.parquet")):
        x = pd.read_parquet(f, columns=["recorded_at_time", "lat", "lon", "siri_route__line_ref", "siri_ride__id"])
        x = x[x.siri_route__line_ref.isin(main.keys())]
        x = x[x.siri_route__line_ref.map(names).isin(URBAN)].drop_duplicates(["siri_ride__id", "recorded_at_time"])
        for rid, g in x.sort_values("recorded_at_time").groupby("siri_ride__id"):
            rid_ = g.siri_route__line_ref.iloc[0]
            if len(g) < 5 or len(main[rid_]) < 3:
                continue
            seq, _, tp, first = match_ride(g, main[rid_], cum[rid_], pos)
            t0 = first.tz_convert("Asia/Jerusalem")
            for k in range(len(seq) - 1):
                if np.isfinite(tp[k]) and np.isfinite(tp[k + 1]):
                    m = (tp[k + 1] - tp[k]) / 60
                    if 0 < m <= MAX_SEG_MIN:
                        h = (t0 + pd.Timedelta(seconds=tp[k])).hour
                        rows.append((seq[k], seq[k + 1], h, m))
        print(f, len(rows), flush=True)
    D = pd.DataFrame(rows, columns=["a", "b", "hour", "min"])
    out = D.groupby(["a", "b", "hour"])["min"].agg(n="size", median="median",
                                                   q25=lambda v: v.quantile(.25), q75=lambda v: v.quantile(.75)).reset_index()
    out["sched"] = [sched.get((a, b), np.nan) for a, b in zip(out.a, out.b, strict=True)]
    out.round(3).to_csv("data/segment_times.csv", index=False)
    D["sched"] = [sched.get((a, b), np.nan) for a, b in zip(D.a, D.b, strict=True)]
    D = D.dropna()
    print(len(D), "segment passes,", out[["a", "b"]].drop_duplicates().shape[0], "segments")
    by_h = D.groupby("hour").apply(lambda g: g["min"].sum() / g.sched.sum(), include_groups=False)
    print("actual / scheduled, by hour:"); print(by_h.round(2).to_string())


if __name__ == "__main__":
    main()
