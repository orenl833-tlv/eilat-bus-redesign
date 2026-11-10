"""Timetable journey planning (connection scan), as a trip-planner app does it: every real departure, the
transfer walks and the walks at both ends. Used to check single trips the frequency-based evaluation only
averages (its wait is half the headway; a timetable has fixed times, and can have timed transfers).

A Network is built from a GTFS (today's extract, or an option's export).
- Today's printed times are scaled per line and period to the measured run times (data/runtime_factor.csv,
  SIRI); an option's export already uses them.
- `realize` draws a delayed copy of the network: each trip gets a departure delay and a run-time deviation
  sampled from real trips (data/ride_delays.csv, SIRI), so connections can be missed as on the street.
- `plan` can require a minimum time at a transfer (getting off, crossing, being at the stop on time).
"""
import io
import zipfile
import zlib

import numpy as np
import pandas as pd

from . import params as P
from .evaluate import walk_min

RUNTIME_FACTOR = 1.24
WALK_MAX_MIN = P.WALK_MAX_M * P.DETOUR / (P.WALK_KMH * 1000 / 60)
TRANSFER_MAX_MIN = P.TRANSFER_WALK_M * P.DETOUR / (P.WALK_KMH * 1000 / 60)
PERIODS = P.PERIODS


def _period(minute):
    h = int(minute // 60) % 24
    return next((k for k, (a, b) in PERIODS.items() if a <= h < b), "19-24")


def base_line(line):
    """'5אx' -> '5', 'A14H' -> 'A14H': the line whose measured delays apply."""
    s = str(line).rstrip("xs").replace("א", "")
    return s


class DelaySampler:
    """Real trips' (departure delay, run ratio) by line and period; the ratio is used relative to its mean,
    which the timetables already contain, so the sampled run-time deviation averages zero."""

    def __init__(self, path="data/ride_delays.csv", min_n=30):
        D = pd.read_csv(path, dtype={"line": str})
        self.pool = {}
        for key, g in list(D.groupby(["line", "period"])) + list(D.groupby(["period"])):
            k = key if isinstance(key, tuple) and len(key) == 2 else ("*", key[0] if isinstance(key, tuple) else key)
            if len(g) >= min_n:
                self.pool[k] = (g.d0.values.clip(-1, None), g.ratio.values / g.ratio.mean())
        self.all = (D.d0.values.clip(-1, None), D.ratio.values / D.ratio.mean())

    def sample(self, line, period, rng):
        d0, mult = self.pool.get((base_line(line), period)) or self.pool.get(("*", period)) or self.all
        i = rng.integers(len(d0))
        return float(d0[i]), float(mult[i])


class Network:
    def __init__(self, stop_times, trip_line, stops, scale=1.0, foot=None):
        """stop_times: trip_id, stop_id, stop_sequence, t (minutes); trip_line: trip_id -> public line;
        scale: a number, or a dict trip_id -> number (run times scaled from each trip's first stop)."""
        self.st = stop_times.sort_values(["trip_id", "stop_sequence"])
        self.line = trip_line
        self.stops = stops
        self.trips = {}
        for tid, g in self.st.groupby("trip_id", sort=False):
            s, t = g.stop_id.values.astype(int), g.t.values.astype(float)
            k = scale.get(tid, RUNTIME_FACTOR) if isinstance(scale, dict) else scale
            self.trips[tid] = (s, t[0] + (t - t[0]) * k)
        self._build({})
        if foot is None:
            ids = list(stops.index)
            la, lo = stops.stop_lat.values, stops.stop_lon.values
            W = walk_min(la[:, None], lo[:, None], la[None, :], lo[None, :])
            foot = {ids[i]: [(ids[j], float(W[i, j])) for j in np.where((W[i] <= TRANSFER_MAX_MIN) & (W[i] > 0))[0]]
                    for i in range(len(ids))}
        self.foot = foot

    def _build(self, delays):
        rows, self.seq = [], {}
        for tid, (s, t) in self.trips.items():
            if tid in delays:
                d0, mult = delays[tid]
                t = t[0] + d0 + (t - t[0]) * mult
            self.seq[tid] = list(s)
            rows += [(t[i], t[i + 1], int(s[i]), int(s[i + 1]), tid) for i in range(len(s) - 1)]
        rows.sort(key=lambda r: r[0])
        self.conn = rows

    def realize(self, sampler, seed, keys=None):
        """A copy of this network with every trip delayed as a real trip of its line and period was. Each
        trip's draw depends only on (seed, its key), so two timetables share their random numbers trip by
        trip (keys: trip_id -> a stable name, e.g. pattern/period/departure number; default the trip_id)."""
        other = object.__new__(Network)
        other.st, other.line, other.stops, other.trips, other.foot = self.st, self.line, self.stops, self.trips, self.foot
        delays = {}
        for tid, (s, t) in self.trips.items():
            k = (keys or {}).get(tid, tid)
            rng = np.random.default_rng([seed, zlib.crc32(str(k).encode())])
            delays[tid] = sampler.sample(self.line.get(tid, ""), _period(t[0]), rng)
        other._build(delays)
        return other

    @classmethod
    def today(cls, gdir, stops, factors="data/runtime_factor.csv"):
        st = pd.read_csv(gdir + "stop_times.csv")
        tr = pd.read_csv(gdir + "trips.csv").merge(pd.read_csv(gdir + "routes.csv")[["route_id", "route_short_name"]], on="route_id")
        st["t"] = st.dep / 60
        line = dict(zip(tr.trip_id, tr.route_short_name.astype(str), strict=True))
        F = pd.read_csv(factors, dtype={"line": str})
        fac = {(r.line, r.period): r.factor for r in F.itertuples()}
        t0 = st.groupby("trip_id").t.min()
        scale = {tid: fac.get((base_line(line[tid]), _period(t)), RUNTIME_FACTOR) for tid, t in t0.items() if tid in line}
        return cls(st, line, stops, scale)

    @classmethod
    def from_zip(cls, path, service, stops, foot=None):
        z = zipfile.ZipFile(path)
        rd = lambda n: pd.read_csv(io.BytesIO(z.read(n)))  # noqa: E731
        tr = rd("trips.txt"); tr = tr[tr.service_id == service]
        st = rd("stop_times.txt"); st = st[st.trip_id.isin(tr.trip_id)].copy()
        st["t"] = (st.arrival_time.str.split(":", expand=True).astype(int) @ [60, 1, 1 / 60]).values
        return cls(st, dict(zip(tr.trip_id, tr.route_id.astype(str), strict=True)), stops, 1.0, foot)

    def plan(self, o_lat, o_lon, d_lat, d_lon, t0, transfer_min=0.0):
        """Earliest arrival leaving (o) at t0 (minutes). Returns dict(arrive, legs) or None; legs are
        ('walk', minutes, to_stop) and ('ride', line, board_stop, dep, alight_stop, arr, n_stops).
        transfer_min: after getting off, the next bus can be boarded only this many minutes later."""
        S = self.stops
        acc = walk_min(o_lat, o_lon, S.stop_lat.values, S.stop_lon.values)
        egr = walk_min(S.stop_lat.values, S.stop_lon.values, d_lat, d_lon)
        best = {}; ready = {}; jp = {}
        for sid, w in zip(S.index, acc, strict=True):
            if w <= WALK_MAX_MIN:
                best[sid] = ready[sid] = t0 + w; jp[sid] = ("start", float(w))
        egress = {sid: float(w) for sid, w in zip(S.index, egr, strict=True) if w <= WALK_MAX_MIN}
        on = {}
        target = np.inf
        for dep, arr, a, b, tid in self.conn:
            if dep < t0:
                continue
            if dep > target:
                break
            if tid in on or ready.get(a, np.inf) <= dep:
                if tid not in on:
                    on[tid] = (a, dep)
                if arr < best.get(b, np.inf):
                    best[b] = arr; jp[b] = ("ride", tid, on[tid][0], on[tid][1], arr)
                    ready[b] = min(ready.get(b, np.inf), arr + transfer_min)
                    if b in egress:
                        target = min(target, arr + egress[b])
                    for c, w in self.foot.get(b, []):
                        if arr + w < best.get(c, np.inf):
                            best[c] = arr + w; jp[c] = ("foot", b, w)
                            ready[c] = min(ready.get(c, np.inf), arr + w + transfer_min)
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
