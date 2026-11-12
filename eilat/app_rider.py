"""A rider with a live bus app (Moovit and the like): sees where every bus is now, not where it will be.

For one realized network (eilat/timetable.py Network.realize: every trip late or early as a real trip of its line,
direction and hour was) and the same network without delays (the timetable):
- app snapshot at time tau: a bus already on its way is predicted to keep its current lateness to the end of its run
  (what apps do); a bus not yet started is predicted on its timetable, or as leaving now if its departure time has
  passed. Snapshots are taken every SNAP minutes and cover the next HORIZON minutes.
- the rider plans on the latest snapshot, walks to the stop and takes that bus as it really runs (if it came early and
  left before they got there, they re-plan from the stop); once off, they open the app again at the transfer stop and
  plan from there (the next bus of the line, another line, or walking): a second bus that comes early or late is waited
  for, or missed, as on the street.
"""
import numpy as np

from .evaluate import walk_min

SNAP, HORIZON = 5.0, 150.0


class AppRider:
    def __init__(self, sched, real, transfer_min=2.0):
        self.sched, self.real, self.tm = sched, real, transfer_min
        self.cache = {}
        self.S = sched.stops

    def snapshot(self, tau):
        tau = np.floor(tau / SNAP) * SNAP
        if tau in self.cache:
            return self.cache[tau]
        if len(self.cache) > 40:
            self.cache.clear()
        sched, real = self.sched, self.real
        rows = []
        for tid, (s, t) in sched.trips.items():
            if t[0] > tau + HORIZON or t[-1] < tau - 60:
                continue
            _, rt = real.realized_times(tid)
            if rt[0] <= tau:                               # on its way: keep the lateness at its last stop
                k = int(np.searchsorted(rt, tau, side="right")) - 1
                pred = np.concatenate([rt[:k + 1], t[k + 1:] + (rt[k] - t[k])])
            else:                                          # not started: timetable, or leaving now if overdue
                pred = t + max(0.0, tau - t[0])
            rows += [(pred[i], pred[i + 1], int(s[i]), int(s[i + 1]), tid) for i in range(len(s) - 1) if pred[i] >= tau - 1]
        rows.sort(key=lambda r: r[0])
        snap = object.__new__(type(sched))
        snap.st, snap.line, snap.stops, snap.trips, snap.foot = sched.st, sched.line, sched.stops, sched.trips, sched.foot
        snap.seq, snap.conn, snap.cont = sched.seq, rows, {}
        self.cache[tau] = snap
        return snap

    def trips(self, o_lat, o_lon, dests, t0):
        """trip() to several destinations from one origin and time: the first plan, on the same snapshot, is one
        scan for all of them."""
        first = self.snapshot(t0).plan_many(o_lat, o_lon, dests, t0, 0.0)
        return [self.trip(o_lat, o_lon, d[0], d[1], t0, r) for d, r in zip(dests, first, strict=True)]

    def trip(self, o_lat, o_lon, d_lat, d_lon, t0, first=False):
        """Door-to-door arrival and the time spent waiting at transfer stops (after the first bus). first: the
        first plan if already made (None = no bus)."""
        lat, lon, t, wait_xfer, rides = o_lat, o_lon, float(t0), 0.0, 0
        direct = float(walk_min(o_lat, o_lon, d_lat, d_lon))
        for step in range(6):
            snap = self.snapshot(t)
            r = first if (step == 0 and first is not False) else snap.plan(lat, lon, d_lat, d_lon, t, self.tm if rides else 0.0)
            walk_rest = float(walk_min(lat, lon, d_lat, d_lon))
            if r is None or r["arrive"] - t >= walk_rest:
                return min(t + walk_rest, t0 + direct), wait_xfer
            legs = r["legs"]
            i = next(k for k, g in enumerate(legs) if g[0] == "ride")
            walk_to = sum(g[1] for g in legs[:i] if g[0] == "walk")
            _, line, a, dep, b, _, _ = legs[i]
            tid = self.find(snap, line, a, b, dep)
            at_stop = t + walk_to
            if tid is None:
                return min(t + walk_rest, t0 + direct), wait_xfer
            s, rt = self.real.realized_times(tid)
            sl = list(s); ia = sl.index(a); ib = sl.index(b, ia + 1)
            lat, lon = float(self.S.stop_lat[a]), float(self.S.stop_lon[a])
            if rt[ia] < at_stop - 1e-9:                    # it came early and left: re-plan from the stop
                t = at_stop
                continue
            if rides:
                wait_xfer += rt[ia] - at_stop
            t = float(rt[ib]); rides += 1
            lat, lon = float(self.S.stop_lat[b]), float(self.S.stop_lon[b])
            if not any(g[0] == "ride" for g in legs[i + 1:]):
                egress = sum(g[1] for g in legs[i + 1:] if g[0] == "walk")
                return min(t + egress, t0 + direct), wait_xfer
            t += self.tm
        return t + float(walk_min(lat, lon, d_lat, d_lon)), wait_xfer

    @staticmethod
    def find(snap, line, a, b, dep):
        """The trip the app proposed: its line, boarding a at the predicted `dep`, going on to b."""
        best = None
        for d0, _, u, _, tid in snap.conn:
            if d0 > dep + 1e-6:
                break
            if u == a and abs(d0 - dep) < 1e-6 and snap.line.get(tid) == line:
                sq = snap.seq[tid]
                if b in sq[sq.index(a) + 1:]:
                    best = tid
        return best
