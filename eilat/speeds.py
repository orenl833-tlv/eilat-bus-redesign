"""Run times by street segment and hour of day, measured from the buses' GPS (data/segment_times.csv, from
analysis/segment_times.py).

minutes(a, b, clock) for the segment from stop a to the next stop b, leaving a at `clock` (minutes after
midnight):
- the measured median for that segment and hour, blended with a prior when it has few passes:
  (n x measured + K x prior) / (n + K);
- prior = the segment's own scheduled minutes x its all-day ratio to schedule x the city's ratio in that
  hour relative to the all-day ratio (so a slow street stays slow, and every street follows the city's day);
- a segment with no measurement: the default the caller gives (an option's period minutes, or the printed
  minutes x the city's ratio for that hour).
run() turns a stop sequence and a departure time into the time at each stop, the clock moving with the bus,
so a trip that starts at 06:50 runs its later segments at 07:00 speeds.
"""
import numpy as np
import pandas as pd

from . import params as P

K = 8.0
MIN_HOUR_PASSES = 500


class Speeds:
    def __init__(self, path="data/segment_times.csv"):
        D = pd.read_csv(path).dropna(subset=["sched"])
        D = D[D.sched > 0]
        w = D.n * D["median"]
        city = (w.groupby(D.hour).sum() / (D.n * D.sched).groupby(D.hour).sum())
        few = D.groupby("hour").n.sum() < MIN_HOUR_PASSES          # e.g. after midnight: the all-day ratio
        self.city_all = float(w.sum() / (D.n * D.sched).sum())
        self.city = {h: float(city[h]) if h in city.index and not few[h] else self.city_all for h in range(24)}
        seg = w.groupby([D.a, D.b]).sum() / (D.n * D.sched).groupby([D.a, D.b]).sum()
        self.seg_ratio = seg.to_dict()
        self.sched = D.groupby(["a", "b"]).sched.first().to_dict()
        self.measured_hours = set(few.index[~few])
        self.cell = {(r.a, r.b, r.hour): (r.n, r.median) for r in D.itertuples()}
        self._cache = {}

    def city_factor(self, clock):
        """The city's run time / printed time in that hour (all-day ratio where an hour has too few passes)."""
        return self.city[int(clock // 60) % 24]

    def minutes(self, a, b, clock, default=None):
        h = int(clock // 60) % 24
        if h not in self.measured_hours:     # no prior by hour: the all-day ratio
            h = -1
        key = (a, b, h)
        if key in self._cache:
            return self._cache[key] if self._cache[key] is not None else default
        m = None
        if (a, b) in self.sched:
            prior = self.sched[(a, b)] * self.seg_ratio[(a, b)] * (self.city[h] if h >= 0 else self.city_all) / self.city_all
            n, med = self.cell.get(key, (0, 0.0))
            m = (n * med + K * prior) / (n + K)
        self._cache[key] = m
        return m if m is not None else default

    def run(self, stops, t0, default, skip=(), p_served=None):
        """Times at each stop of `stops` leaving the first at t0. default(i, clock) gives segment i's minutes
        where it was not measured; a stop in `skip` (not the ends) saves the stopping time on the segment
        before it, as in Pattern.times."""
        t = [float(t0)]
        for i in range(len(stops) - 1):
            m = self.minutes(stops[i], stops[i + 1], t[-1])
            if m is None:
                m = default(i, t[-1])
            s = stops[i + 1]
            if s in skip and i + 1 < len(stops) - 1:
                m = max(m - P.STOP_COST_S / 60 * (p_served or {}).get(s, 0.7), 0.1)
            t.append(t[-1] + m)
        return np.array(t)

    def pattern_run(self, p, t0):
        """Times at every stop of a network Pattern (including the stops it passes) leaving at t0: measured
        segment times at each hour, the pattern's period minutes where a segment is not measured, and the
        stopping time saved at its skipped stops."""
        def default(i, clock):
            h = int(clock // 60) % 24
            q = next((k for k, (a, b) in P.PERIODS.items() if a <= h < b), "19-24")
            seg = p.seg_min.get(q) or next(iter(p.seg_min.values()))
            return seg[i]
        return self.run(p.stops, t0, default, p.skip, p.p_served)
