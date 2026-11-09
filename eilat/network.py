"""A bus network = a list of line patterns. Each pattern is an ordered list of stops (with the stops it
passes without stopping), a running time per segment and period, and a headway per period.

- from_gtfs(): today's network, with run times corrected to what SIRI measured (runtime_factor.csv).
- Pattern.times(period): segment minutes; a skipped stop saves STOP_COST_S x P(stop would be served).
- fleet(): buses needed per period and bus-hours per day, with terminal layovers.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import params as P

G = "data/gtfs_eilat"


@dataclass
class Pattern:
    name: str                       # e.g. "5/0" (line / direction) or a candidate id
    line: str                       # lines share a vehicle pool: fleet is counted per line
    stops: list[int]                # stop_ids in order, including passed-without-stopping ones
    seg_min: dict[str, list[float]]  # period -> minutes for each of len(stops)-1 segments (with stopping)
    headway: dict[str, float]       # period -> minutes between buses (inf = no service)
    skip: set[int] = field(default_factory=set)   # stops passed without stopping
    p_served: dict[int, float] = field(default_factory=dict)  # stop -> share of trips that stop there

    def times(self, period):
        seg = list(self.seg_min[period])
        for i, s in enumerate(self.stops[1:-1], start=1):
            if s in self.skip:  # passing a stop instead of stopping saves time on the segment before it
                seg[i - 1] = max(seg[i - 1] - P.STOP_COST_S / 60 * self.p_served.get(s, 0.7), 0.1)
        return seg

    def run_min(self, period):
        return float(sum(self.times(period)))


def _period(sec):
    h = (sec // 3600) % 24
    return next((k for k, (a, b) in P.PERIODS.items() if a <= h < b), None)


def from_gtfs(scale_runtime=True):
    """Today's urban network, one pattern per (line, direction), headways per period from the timetable."""
    st = pd.read_csv(f"{G}/stop_times.csv").sort_values(["trip_id", "stop_sequence"])
    tr = pd.read_csv(f"{G}/trips.csv").merge(pd.read_csv(f"{G}/routes.csv")[["route_id", "route_short_name"]], on="route_id")
    tr["line"] = tr.route_short_name.astype(str)
    fac = pd.read_csv("data/runtime_factor.csv", dtype={"line": str}) if scale_runtime else None
    pats = []
    for (line, d), trips in tr.groupby(["line", "direction_id"]):
        sts = st[st.trip_id.isin(trips.trip_id)]
        seqs = sts.groupby("trip_id").stop_id.apply(tuple)
        main = seqs.value_counts().index[0]
        first = sts.groupby("trip_id").dep.min()
        seg = {}
        same = seqs[seqs == main].index
        x = sts[sts.trip_id.isin(same)].copy()
        x["nxt_arr"] = x.groupby("trip_id").arr.shift(-1)
        x["seg"] = (x.nxt_arr - x.dep) / 60
        x["k"] = x.groupby("trip_id").cumcount()
        x["period"] = x.trip_id.map(first).map(_period)
        base = x.dropna(subset=["seg"]).groupby("k").seg.median().reindex(range(len(main) - 1)).fillna(1.0).values
        hw = {}
        for p, (a, b) in P.PERIODS.items():
            n = ((first // 3600 >= a) & (first // 3600 < b)).sum()
            hw[p] = (b - a) * 60 / n if n else math.inf
            f = 1.0
            if fac is not None:
                m = fac[(fac.line == line.replace("א", "")) & (fac.period == p)]
                f = float(m.factor.iloc[0]) if len(m) else float(fac[fac.line == line.replace("א", "")].factor.median()
                                                                 if (fac.line == line.replace("א", "")).any() else fac.factor.median())
            seg[p] = list(np.maximum(base, 0.1) * f)
        pats.append(Pattern(name=f"{line}/{d}", line=line, stops=list(main), seg_min=seg, headway=hw))
    return pats


def fleet(pats, periods=None):
    """Buses in use per period (incl. layovers) and bus-hours per day.

    A line's buses in a period = ceil(sum over its patterns of (run + layover) / headway). Layover per one-way
    trip = max(LAYOVER_SHARE x run, LAYOVER_MIN)."""
    periods = periods or P.PERIODS
    by_line = {}
    for pt in pats:
        for p in periods:
            h = pt.headway.get(p, math.inf)
            if not math.isfinite(h):
                continue
            run = pt.run_min(p)
            lay = max(P.LAYOVER_SHARE * run, P.LAYOVER_MIN)
            by_line.setdefault((pt.line, p), 0.0)
            by_line[(pt.line, p)] += (run + lay) / h
    buses = {p: sum(math.ceil(v - 1e-9) for (ln, pp), v in by_line.items() if pp == p) for p in periods}
    # bus-hours from the fractional need (ceil per period would overstate a whole period's worth)
    hours = sum(v * (P.PERIODS[pp][1] - P.PERIODS[pp][0]) for (ln, pp), v in by_line.items())
    return buses, hours
