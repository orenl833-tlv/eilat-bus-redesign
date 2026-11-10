"""Timetable journey planning (connection scan), as a trip-planner app does it: every real departure, the
transfer walks and the walks at both ends. Used to check single trips the frequency-based evaluation only
averages (its wait is half the headway; a timetable has fixed times, and can have timed transfers).

A Network is built from a GTFS (today's extract, or an option's export). Today's printed times are scaled to
the measured run times (SIRI: trips take ~1.24 x the timetable), so both sides use measured speeds.
"""
import io
import zipfile

import numpy as np
import pandas as pd

from . import params as P
from .evaluate import walk_min

RUNTIME_FACTOR = 1.24
WALK_MAX_MIN = P.WALK_MAX_M * P.DETOUR / (P.WALK_KMH * 1000 / 60)
TRANSFER_MAX_MIN = P.TRANSFER_WALK_M * P.DETOUR / (P.WALK_KMH * 1000 / 60)


class Network:
    def __init__(self, stop_times, trip_line, stops, scale=1.0):
        """stop_times: trip_id, stop_id, stop_sequence, t (minutes); trip_line: trip_id -> public line."""
        st = stop_times.sort_values(["trip_id", "stop_sequence"])
        rows, self.seq = [], {}
        for tid, g in st.groupby("trip_id", sort=False):
            s, t = g.stop_id.values, g.t.values.astype(float)
            self.seq[tid] = [int(x) for x in s]
            t = t[0] + (t - t[0]) * scale
            rows += [(t[i], t[i + 1], int(s[i]), int(s[i + 1]), tid) for i in range(len(s) - 1)]
        rows.sort(key=lambda r: r[0])
        self.conn = rows
        self.line = trip_line
        self.stops = stops
        ids = list(stops.index)
        la, lo = stops.stop_lat.values, stops.stop_lon.values
        W = walk_min(la[:, None], lo[:, None], la[None, :], lo[None, :])
        self.foot = {ids[i]: [(ids[j], float(W[i, j])) for j in np.where((W[i] <= TRANSFER_MAX_MIN) & (W[i] > 0))[0]]
                     for i in range(len(ids))}

    @classmethod
    def today(cls, gdir, stops):
        st = pd.read_csv(gdir + "stop_times.csv")
        tr = pd.read_csv(gdir + "trips.csv").merge(pd.read_csv(gdir + "routes.csv")[["route_id", "route_short_name"]], on="route_id")
        st["t"] = st.dep / 60
        return cls(st, dict(zip(tr.trip_id, tr.route_short_name.astype(str), strict=True)), stops, RUNTIME_FACTOR)

    @classmethod
    def from_zip(cls, path, service, stops):
        z = zipfile.ZipFile(path)
        rd = lambda n: pd.read_csv(io.BytesIO(z.read(n)))  # noqa: E731
        tr = rd("trips.txt"); tr = tr[tr.service_id == service]
        st = rd("stop_times.txt"); st = st[st.trip_id.isin(tr.trip_id)].copy()
        st["t"] = (st.arrival_time.str.split(":", expand=True).astype(int) @ [60, 1, 1 / 60]).values
        return cls(st, dict(zip(tr.trip_id, tr.route_id.astype(str), strict=True)), stops, 1.0)

    def plan(self, o_lat, o_lon, d_lat, d_lon, t0):
        """Earliest arrival leaving (o) at t0 (minutes). Returns dict(arrive, legs) or None; legs are
        ('walk', minutes, to_stop) and ('ride', line, board_stop, dep, alight_stop, arr, n_stops)."""
        S = self.stops
        acc = walk_min(o_lat, o_lon, S.stop_lat.values, S.stop_lon.values)
        egr = walk_min(S.stop_lat.values, S.stop_lon.values, d_lat, d_lon)
        best = {}; jp = {}
        for sid, w in zip(S.index, acc, strict=True):
            if w <= WALK_MAX_MIN:
                best[sid] = t0 + w; jp[sid] = ("start", float(w))
        egress = {sid: float(w) for sid, w in zip(S.index, egr, strict=True) if w <= WALK_MAX_MIN}
        on = {}
        target = np.inf
        for dep, arr, a, b, tid in self.conn:
            if dep < t0:
                continue
            if dep > target:
                break
            if tid in on or best.get(a, np.inf) <= dep:
                if tid not in on:
                    on[tid] = (a, dep)
                if arr < best.get(b, np.inf):
                    best[b] = arr; jp[b] = ("ride", tid, on[tid][0], on[tid][1], arr)
                    if b in egress:
                        target = min(target, arr + egress[b])
                    for c, w in self.foot.get(b, []):
                        if arr + w < best.get(c, np.inf):
                            best[c] = arr + w; jp[c] = ("foot", b, w)
        reach = [(best[s] + egress[s], s) for s in egress if s in best and jp[s][0] != "start"]
        if not reach:
            return None
        arrive, last = min(reach)
        legs, x = [("walk", egress[last], None)], last
        while jp[x][0] != "start":
            k = jp[x]
            if k[0] == "foot":
                legs.append(("walk", k[2], x)); x = k[1]
            else:
                q = self.seq[k[1]]
                n = q.index(x, q.index(k[2]) + 1) - q.index(k[2]) if x in q[q.index(k[2]) + 1:] else None
                legs.append(("ride", self.line[k[1]], k[2], k[3], x, k[4], n)); x = k[2]
        legs.append(("walk", jp[x][1], x))
        return dict(arrive=arrive, legs=list(reversed(legs)))
