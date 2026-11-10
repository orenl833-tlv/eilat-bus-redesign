"""Write each option as a GTFS feed, so planners can open it in their own tools (Remix, OTP, gtfs-kit ...).

One feed for the recommended plan (option 3, exports/gtfs_eilat_proposal.zip), weekdays (Sun-Thu) only, three timetables by season via
calendar_dates.txt over one year from 1 Nov 2026 (no holidays marked):
  winter Nov-Mar, spring/autumn Apr-Jun + Sep-Oct, summer holiday Jul-Aug.
- Trips: every `headway` minutes in each period, the second direction offset by half a headway (as in
  scripts/blocking.py); the evening ends at 23:00, plus the 5 shift-change trips for the hotels and Yoseftal
  (scripts/shift_trips.py). Times between stops are measured: each street segment's GPS (SIRI) run time at the
  hour the bus passes it (eilat/speeds.py), so 06:00 trips are faster than noon trips. Stops a line passes without stopping are left out of its stop_times.
- School lines 80-82: today's real trips and times, not in the summer holiday.
- block_id: the vehicle blocks of scripts/blocking.py (which bus runs which trip).
- Line numbers are the public ones (a variant keeps its number; line 7 is new). Friday and Saturday are not
  included: keep today's (see REDESIGN.md).

Usage: PYTHONPATH=.:scripts python3 scripts/export_gtfs.py   Output: exports/gtfs_eilat_proposal.zip
"""
import datetime as dt
import io
import math
import zipfile

import pandas as pd

import blocking as BL
import shift_trips as SHT
from eilat import params as P
from eilat.speeds import Speeds
from export_page import public_name

EVENING_END = 23   # the recommended package: last departures before 23:00, plus the shift-change trips
PLAN = "full_peak-3_warm"   # the recommended plan (option 3)
OUT = "exports/gtfs_eilat_proposal.zip"
SEASON_MONTHS = {"winter": [11, 12, 1, 2, 3], "spring_autumn": [4, 5, 6, 9, 10], "summer": [7, 8]}
START = dt.date(2026, 11, 1)
SPEEDS = Speeds()


def hms(m):
    s = int(round(m * 60)); return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def season_dates():
    out = []
    for i in range(365):
        d = START + dt.timedelta(days=i)
        if d.weekday() in (6, 0, 1, 2, 3):   # Sun-Thu
            se = next(k for k, ms in SEASON_MONTHS.items() if d.month in ms)
            out.append(dict(service_id=f"weekday_{se}", date=d.strftime("%Y%m%d"), exception_type=1))
    return pd.DataFrame(out)


def option_trips(tag, se, names):
    """Trips and stop times of an option's non-school lines in a season."""
    trips, times = [], []
    net = BL.option_net(tag, se)
    shift = SHT.shift_trips(net, SHT.hotel_stops())
    for p in net:
        if p.line in BL.SCHOOL:
            continue
        disp, _ = public_name(p.line)
        dr = "1" if "/1" in p.name else "0"
        off = 0.5 if dr == "1" else 0.0
        for q, (a, b) in P.PERIODS.items():
            h = p.headway.get(q, math.inf)
            if not math.isfinite(h):
                continue
            t = a * 60 + off * h
            b = min(b, EVENING_END)
            starts = []
            while t < b * 60:
                starts.append(t); t += h
            if q == "19-24":
                starts += [r.start for r in shift.itertuples() if r.pattern == p.name]
            for t in starts:
                run = SPEEDS.pattern_run(p, t)
                tid = f"{tag}_{se}_{p.name}_{len(trips)}"
                trips.append(dict(route_id=disp, service_id=f"weekday_{se}", trip_id=tid, trip_headsign=names.get(p.stops[-1], ""),
                                  direction_id=dr, line=p.line, start=t, end=float(run[-1]), o=p.stops[0], d=p.stops[-1]))
                k = 0
                for i, s in enumerate(p.stops):
                    cum = run[i]
                    if s in p.skip and 0 < i < len(p.stops) - 1:
                        continue
                    k += 1
                    times.append(dict(trip_id=tid, arrival_time=hms(cum), departure_time=hms(cum), stop_id=s, stop_sequence=k))
    return pd.DataFrame(trips), pd.DataFrame(times)


def school_trips(se):
    if se == "summer":
        return pd.DataFrame(), pd.DataFrame()
    g = "data/gtfs_eilat/"
    r = pd.read_csv(g + "routes.csv")[["route_id", "route_short_name"]]
    tr = pd.read_csv(g + "trips.csv").merge(r, on="route_id")
    tr = tr[tr.route_short_name.astype(str).isin(BL.SCHOOL)]
    stt = pd.read_csv(g + "stop_times.csv").sort_values(["trip_id", "stop_sequence"])
    stt = stt[stt.trip_id.isin(tr.trip_id)]
    agg = stt.groupby("trip_id").agg(start=("dep", "min"), end=("arr", "max"), o=("stop_id", "first"), d=("stop_id", "last"))
    tr = tr.set_index("trip_id").join(agg).reset_index()
    T = pd.DataFrame(dict(route_id=tr.route_short_name.astype(str), service_id=f"weekday_{se}", trip_id=f"school_{se}_" + tr.trip_id,
                          trip_headsign=tr.trip_headsign, direction_id=tr.direction_id.astype(str), line=tr.route_short_name.astype(str),
                          start=tr.start / 60, end=tr.end / 60, o=tr.o, d=tr.d))
    S = stt.assign(trip_id=f"school_{se}_" + stt.trip_id)[["trip_id", "arrival_time", "departure_time", "stop_id", "stop_sequence"]]
    return T, S


def build(tag, stops):
    names = dict(zip(stops.stop_id, stops.stop_name, strict=True))
    st = stops.set_index("stop_id")
    T_all, S_all = [], []
    for se in P.SEASONS:
        T, S = option_trips(tag, se, names)
        T2, S2 = school_trips(se)
        T = pd.concat([T, T2], ignore_index=True); S = pd.concat([S, S2], ignore_index=True)
        # vehicle blocks, as in scripts/blocking.py
        _, _, blocks = BL.block(T[T.o.isin(st.index) & T.d.isin(st.index)].reset_index(drop=True), st)
        bid = {tid: f"{se}_bus{k + 1:02d}" for k, b in enumerate(blocks) for tid in b.trip_id}
        T["block_id"] = T.trip_id.map(bid)
        T_all.append(T); S_all.append(S)
    T = pd.concat(T_all, ignore_index=True); S = pd.concat(S_all, ignore_index=True)
    used = stops[stops.stop_id.isin(S.stop_id)][["stop_id", "stop_code", "stop_name", "stop_lat", "stop_lon"]]
    routes = []
    for rid, g in T.groupby("route_id"):
        notes = sorted({public_name(x)[1] for x in g.line} - {""})
        routes.append(dict(route_id=rid, agency_id="proposal", route_short_name=rid, route_long_name=" · ".join(notes), route_type=3))
    files = {
        "agency.txt": pd.DataFrame([dict(agency_id="proposal",
                                         agency_name="Eilat bus network proposal (research model, not an operator timetable)",
                                         agency_url="https://github.com/orenl833-tlv/test-claude", agency_timezone="Asia/Jerusalem", agency_lang="he")]),
        "stops.txt": used, "routes.txt": pd.DataFrame(routes),
        "trips.txt": T[["route_id", "service_id", "trip_id", "trip_headsign", "direction_id", "block_id"]],
        "stop_times.txt": S, "calendar_dates.txt": season_dates(),
        "feed_info.txt": pd.DataFrame([dict(feed_publisher_name="eilat-transit research model", feed_publisher_url="https://github.com/orenl833-tlv/test-claude",
                                            feed_lang="he", feed_start_date="20261101", feed_end_date="20271031", feed_version=tag)]),
    }
    check(files)
    path = OUT
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for n, df in files.items():
            buf = io.StringIO(); df.to_csv(buf, index=False); z.writestr(n, buf.getvalue())
    return path, {se: int((T.service_id == f"weekday_{se}").sum()) for se in P.SEASONS}


def check(f):
    """Basic validity: every reference resolves, stop sequences and times increase, every trip has a bus."""
    t, s = f["trips.txt"], f["stop_times.txt"]
    assert t.trip_id.is_unique
    assert set(t.route_id) <= set(f["routes.txt"].route_id)
    assert set(t.service_id) <= set(f["calendar_dates.txt"].service_id)
    assert set(s.trip_id) == set(t.trip_id)
    assert set(s.stop_id) <= set(f["stops.txt"].stop_id)
    assert t.block_id.notna().all(), "a trip without a bus"
    sec = s.arrival_time.str.split(":", expand=True).astype(int) @ [3600, 60, 1]
    s2 = s.assign(sec=sec.values).sort_values(["trip_id", "stop_sequence"])
    assert (s2.groupby("trip_id").stop_sequence.apply(lambda x: x.is_unique)).all()
    assert (s2.groupby("trip_id").sec.apply(lambda x: x.is_monotonic_increasing)).all()
    assert (s2.groupby("trip_id").size() >= 2).all()


def main():
    stops = pd.read_csv("data/stops_all.csv")
    print(*build(PLAN, stops), flush=True)


if __name__ == "__main__":
    main()
