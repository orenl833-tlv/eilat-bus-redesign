"""Timetable journey planning (connection scan), as a trip-planner app does it: every real departure, the
transfer walks and the walks at both ends. Used to check single trips the frequency-based evaluation only
averages (its wait is half the headway; a timetable has fixed times, and can have timed transfers).

A Network is built from a GTFS (today's extract, or an option's export).
- Run times are the buses' measured times on each street segment at that hour (eilat/speeds.py, from GPS):
  today's printed times are replaced by them; an option's export is built with them.
- `realize` draws a delayed copy of the network: each trip gets a departure delay and a run-time deviation
  sampled from real trips of its line at that hour (data/ride_delays.csv, SIRI), so connections can be
  missed as on the street.
- `plan` can require a minimum time at a transfer (getting off, crossing, being at the stop on time).
"""
import io
import zipfile
import zlib

import os

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


def delay_key(line, direction):
    """'3', 1 -> '3/1'; a plan variant's suffix (one trailing 'x' skipping or 's' straightened, after a digit
    or 'א') is dropped; '5א' stays itself (its own measured line)."""
    s = str(line)
    if len(s) > 1 and s[-1] in "xs" and (s[-2].isdigit() or s[-2] == "א"):
        s = s[:-1]
    return f"{s}/{direction}"


class DelaySampler:
    """Real trips' (departure delay, run ratio) from the most specific pool with at least min_n rides: the
    line and direction in that hour, in that period, in all hours; then all lines in that hour, then all.
    The line comes first because lines differ much more than hours do (1, 2 and 15 start ~3 min late,
    3 and 4 on time), and the direction matters (a return trip inherits the outbound trip's lateness).
    d0 is measured against the same typical run times the timetable uses, so it is added as is; the ratio is
    relative to its pool's median (the timetable has the median run time of that hour)."""

    def __init__(self, path="data/ride_delays.csv", min_n=30):
        D = pd.read_csv(path, dtype={"line": str})
        D["key"] = [delay_key(ln, d) for ln, d in zip(D.line, D.direction, strict=True)]
        groups = [(("h", k, h), g) for (k, h), g in D.groupby(["key", "hour"])]
        groups += [(("p", k, q), g) for (k, q), g in D.groupby(["key", "period"])]
        groups += [(("a", k, None), g) for k, g in D.groupby("key")]
        groups += [(("h", "*", h), g) for h, g in D.groupby("hour")]
        # a line with no history of its own (the new lines) is not given the all-lines average: it draws from
        # the late half of today's lines (by mean start delay), so new lines are not assumed more punctual
        # than the lines they replace. NEW_LINE_DELAY=all restores the old all-lines pool.
        late = D.groupby("key").d0.mean()
        L = D[D.key.isin(late[late >= late.median()].index)]
        groups += [(("h", "late", h), g) for h, g in L.groupby("hour")]
        self.new_pool = "late" if os.environ.get("NEW_LINE_DELAY", "late") == "late" else "*"
        self.known = set(D.key)
        self.pool = {k: (g.d0.values, g.ratio.values / g.ratio.median()) for k, g in groups if len(g) >= min_n}
        self.all = (D.d0.values, D.ratio.values / D.ratio.median())

    def sample(self, key, clock, rng):
        h, q = int(clock // 60) % 24, _period(clock)
        fall = "*" if key in self.known else self.new_pool
        d0, mult = next((self.pool[k] for k in (("h", key, h), ("p", key, q), ("a", key, None), ("h", fall, h), ("h", "*", h))
                         if k in self.pool), self.all)
        i = rng.integers(len(d0))
        return float(d0[i]), float(mult[i])


class Network:
    def __init__(self, stop_times, trip_line, stops, scale=1.0, foot=None, speeds=None):
        """stop_times: trip_id, stop_id, stop_sequence, t (minutes); trip_line: trip_id -> public line;
        scale: a number, or a dict trip_id -> number (run times scaled from each trip's first stop);
        speeds: a Speeds; if given, each trip's times are rebuilt from its first departure with the measured
        segment times at that hour (a segment without measurements keeps its given minutes x scale)."""
        self.st = stop_times.sort_values(["trip_id", "stop_sequence"])
        self.line = trip_line
        self.stops = stops
        self.trips = {}
        for tid, g in self.st.groupby("trip_id", sort=False):
            s, t = g.stop_id.values.astype(int), g.t.values.astype(float)
            k = scale.get(tid, RUNTIME_FACTOR) if isinstance(scale, dict) else scale
            if speeds is not None:
                d = np.diff(t)
                t = speeds.run(list(s), t[0], lambda i, c, d=d, k=k: d[i] * k)
            else:
                t = t[0] + (t - t[0]) * k
            self.trips[tid] = (s, t)
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
                lane = getattr(self, "lane", None)
                if lane:      # a bus lane: its segments run with LANE_VAR of the ride's deviation
                    seg = np.diff(t)
                    k = np.array([self.lane_var if (int(s[i]), int(s[i + 1])) in lane else 1.0 for i in range(len(s) - 1)])
                    t = t[0] + d0 + np.concatenate([[0.0], np.cumsum(seg * (1 + (mult - 1) * k))])
                else:
                    t = t[0] + d0 + (t - t[0]) * mult
            self.seq[tid] = list(s)
            rows += [(t[i], t[i + 1], int(s[i]), int(s[i + 1]), tid) for i in range(len(s) - 1)]
        rows.sort(key=lambda r: r[0])
        self.conn = rows

    def realize(self, sampler, seed, keys=None, dkey=None):
        """A copy of this network with every trip delayed as a real trip of its line and period was. Each
        trip's draw depends only on (seed, its key), so two timetables share their random numbers trip by
        trip (keys: trip_id -> a stable name, e.g. pattern/period/departure number; default the trip_id).
        dkey: trip_id -> its delay pool key, 'line/direction' (default self.dkey, else the line)."""
        dkey = dkey if dkey is not None else getattr(self, "dkey", {})
        other = object.__new__(Network)
        other.st, other.line, other.stops, other.trips, other.foot = self.st, self.line, self.stops, self.trips, self.foot
        other.dkey = dkey
        other.cont = getattr(self, "cont", {})
        other.lane, other.lane_var = getattr(self, "lane", None), getattr(self, "lane_var", 1.0)
        delays = {}
        other.delays = delays
        for tid, (s, t) in self.trips.items():
            k = (keys or {}).get(tid, tid)
            rng = np.random.default_rng([seed, zlib.crc32(str(k).encode())])
            delays[tid] = sampler.sample(dkey.get(tid, self.line.get(tid, "")), t[0], rng)
        other._build(delays)
        return other

    def realized_times(self, tid):
        """A trip's stop times in this (realized) network: the timetable's, delayed as realize() drew them."""
        s, t = self.trips[tid]
        d = getattr(self, "delays", {}).get(tid)
        return s, (t if d is None else t[0] + d[0] + (t - t[0]) * d[1])

    def committed(self, sched, o_lat, o_lon, d_lat, d_lon, t0, transfer_min=0.0, r=False):
        """Door-to-door arrival of a rider who does NOT know the future: at t0 they plan on the timetable
        (`sched`, the same network without delays) and commit to its first bus line; then the buses run as in
        this realized network. They take the first bus of that line that comes to the boarding stop after they
        get there and goes to their alighting stop; once off it they see live times and re-plan from there (or
        walk). Returns the arrival, or None if no bus gets them there (walk)."""
        if r is False:          # the timetable plan, unless made in advance (sched.plan_many)
            r = sched.plan(o_lat, o_lon, d_lat, d_lon, t0, transfer_min)
        if r is None:
            return None
        legs = r["legs"]
        i = next(k for k, g in enumerate(legs) if g[0] == "ride")
        walk_to = sum(g[1] for g in legs[:i] if g[0] == "walk")
        _, line, a, _, b, _, _ = legs[i]
        ready = t0 + walk_to
        best = None
        for tid, (s, _) in self.trips.items():
            if self.line.get(tid) != line:
                continue
            sl = list(s)
            if a not in sl or b not in sl[sl.index(a) + 1:]:
                continue
            _, tt = self.realized_times(tid)
            ia = sl.index(a); ib = sl.index(b, ia + 1)
            if tt[ia] >= ready and (best is None or tt[ia] < best[0]):
                best = (tt[ia], tt[ib])
        if best is None:
            return None
        ta = best[1]
        S = self.stops
        b_lat, b_lon = float(S.stop_lat[b]), float(S.stop_lon[b])
        rest = [g for g in legs[i + 1:] if g[0] == "ride"]
        walk_end = float(walk_min(b_lat, b_lon, d_lat, d_lon))
        if not rest:
            return ta + sum(g[1] for g in legs[i + 1:] if g[0] == "walk")
        r2 = self.plan(b_lat, b_lon, d_lat, d_lon, ta + transfer_min, transfer_min)
        return min(ta + walk_end, r2["arrive"]) if r2 else ta + walk_end

    @classmethod
    def today(cls, gdir, stops, speeds=None, foot=None):
        """Today's timetable as the buses really run it: each trip leaves at its printed time, and runs each
        segment in the measured time for that hour (a segment without measurements: printed x the city's
        ratio for that hour)."""
        from .speeds import Speeds
        sp = speeds or Speeds()
        st = pd.read_csv(gdir + "stop_times.csv")
        tr = pd.read_csv(gdir + "trips.csv").merge(pd.read_csv(gdir + "routes.csv")[["route_id", "route_short_name"]], on="route_id")
        st["t"] = st.dep / 60
        line = dict(zip(tr.trip_id, tr.route_short_name.astype(str), strict=True))
        t0 = st.groupby("trip_id").t.min()
        scale = {tid: sp.city_factor(t) for tid, t in t0.items() if tid in line}
        net = cls(st, line, stops, scale, foot, sp)
        net.dkey = {t: delay_key(ln, d) for t, ln, d in zip(tr.trip_id, tr.route_short_name.astype(str), tr.direction_id, strict=True)}
        return net

    @classmethod
    def from_zip(cls, path, service, stops, foot=None):
        z = zipfile.ZipFile(path)
        rd = lambda n: pd.read_csv(io.BytesIO(z.read(n)))  # noqa: E731
        tr = rd("trips.txt"); tr = tr[tr.service_id == service]
        st = rd("stop_times.txt"); st = st[st.trip_id.isin(tr.trip_id)].copy()
        st["t"] = (st.arrival_time.str.split(":", expand=True).astype(int) @ [60, 1, 1 / 60]).values
        net = cls(st, dict(zip(tr.trip_id, tr.route_id.astype(str), strict=True)), stops, 1.0, foot)
        net.dkey = {t: delay_key(r, d) for t, r, d in zip(tr.trip_id, tr.route_id.astype(str), tr.direction_id, strict=True)}
        return net

    def arrivals(self, o_lat, o_lon, dests, t0, transfer_min=0.0, horizon=np.inf, perceived=False):
        """Earliest arrival at each of several destinations [(lat, lon), ...] leaving (o) at t0: one scan
        for all of them (same arrivals as plan() one by one). horizon: stop scanning at t0 + horizon (a
        trip longer than that is not wanted, e.g. it would be walked); a destination not reached by bus is
        NaN. perceived=True: (arrival, perceived minutes of that fastest trip) per destination, perceived =
        in-vehicle + W_WALK x walk + W_WAIT x wait + TRANSFER_PENALTY per transfer (as Base.perceived)."""
        S = self.stops
        acc = walk_min(o_lat, o_lon, S.stop_lat.values, S.stop_lon.values)
        best = {}; ready = {}; rode = set(); lab = {}          # lab: stop -> (walk, in-vehicle, rides) of its best
        for sid, w in zip(S.index, acc, strict=True):
            if w <= WALK_MAX_MIN:
                best[sid] = ready[sid] = t0 + w; lab[sid] = (float(w), 0.0, 0)
        on = {}
        cont = getattr(self, "cont", {})               # trip -> the trip its bus ran just before (a pulse hub)
        end = t0 + horizon
        for dep, arr, a, b, tid in self.conn:
            if dep < t0:
                continue
            if dep > end:
                break
            prev = cont.get(tid)
            if prev is not None and tid not in on and prev in on and self.seq[prev][-1] == a:
                on[tid] = on[prev]                     # the same bus going on: whoever is aboard stays seated
            if tid in on or ready.get(a, np.inf) <= dep:
                if tid not in on:
                    on[tid] = (lab.get(a, (0.0, 0.0, 0)), dep)
                if arr < best.get(b, np.inf):          # as in plan(): a stop counts once a bus improves it
                    (wk, iv, nr), d0 = on[tid]
                    best[b] = arr; rode.add(b); lab[b] = (wk, iv + arr - d0, nr + 1)
                    ready[b] = min(ready.get(b, np.inf), arr + transfer_min)
                    for c, w in self.foot.get(b, []):
                        if arr + w < best.get(c, np.inf):
                            best[c] = arr + w; rode.add(c); lab[c] = (wk + w, iv + arr - d0, nr + 1)
                            ready[c] = min(ready.get(c, np.inf), arr + w + transfer_min)
        out = []
        for d_lat, d_lon in dests:
            egr = walk_min(S.stop_lat.values, S.stop_lon.values, d_lat, d_lon)
            v = [(best[s] + e, s, e) for s, e in zip(S.index, egr, strict=True) if e <= WALK_MAX_MIN and s in rode]
            if not v:
                out.append((np.nan, np.nan) if perceived else np.nan)
                continue
            a, s_, e = min(v)
            if not perceived:
                out.append(a); continue
            wk, iv, nr = lab[s_]
            wk += e
            wait = max(a - t0 - wk - iv, 0.0)
            out.append((a, iv + P.W_WALK * wk + P.W_WAIT * wait + P.TRANSFER_PENALTY * max(nr - 1, 0)))
        return out

    def plan_many(self, o_lat, o_lon, dests, t0, transfer_min=0.0):
        """plan() to several destinations [(lat, lon), ...] from one scan: the same result for each as plan()
        one by one (labels only improve, and the scan stops once every destination's best arrival is passed)."""
        S = self.stops
        acc = walk_min(o_lat, o_lon, S.stop_lat.values, S.stop_lon.values)
        best = {}; ready = {}; jp = {}
        for sid, w in zip(S.index, acc, strict=True):
            if w <= WALK_MAX_MIN:
                best[sid] = ready[sid] = t0 + w; jp[sid] = ("start", float(w))
        egress, by_stop = [], {}
        for k, (d_lat, d_lon) in enumerate(dests):
            egr = walk_min(S.stop_lat.values, S.stop_lon.values, d_lat, d_lon)
            e = {sid: float(w) for sid, w in zip(S.index, egr, strict=True) if w <= WALK_MAX_MIN}
            egress.append(e)
            for sid, w in e.items():
                by_stop.setdefault(sid, []).append((k, w))
        target = [np.inf] * len(dests)
        end = np.inf
        on = {}
        for dep, arr, a, b, tid in self.conn:
            if dep < t0:
                continue
            if dep > end:
                break
            if tid in on or ready.get(a, np.inf) <= dep:
                if tid not in on:
                    on[tid] = (a, dep)
                if arr < best.get(b, np.inf):
                    best[b] = arr; jp[b] = ("ride", tid, on[tid][0], on[tid][1], arr)
                    ready[b] = min(ready.get(b, np.inf), arr + transfer_min)
                    if b in by_stop:
                        for k, w in by_stop[b]:
                            target[k] = min(target[k], arr + w)
                        end = max(target)
                    for c, w in self.foot.get(b, []):
                        if arr + w < best.get(c, np.inf):
                            best[c] = arr + w; jp[c] = ("foot", b, w)
                            ready[c] = min(ready.get(c, np.inf), arr + w + transfer_min)
        out = []
        for e in egress:
            reach = [(best[s] + e[s], s) for s in e if s in best and jp[s][0] != "start"]
            out.append(self._legs(jp, e, min(reach)) if reach else None)
        return out

    def _legs(self, jp, egress, best_pair):
        arrive, last = best_pair
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
