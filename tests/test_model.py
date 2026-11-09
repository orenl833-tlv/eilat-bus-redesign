"""Tests on a tiny synthetic network (no data files needed).

Stops A-B-C-D on a straight street ~400 m apart; points: home next to A, work next to D, and a point
between A and B. Each test pins one property the redesign depends on, including the two bugs found and fixed
(a "bus" trip with no ride in it; riders not sharing common lines).
"""
import math

import numpy as np
import pandas as pd
import pytest

from eilat import params as P
from eilat.evaluate import Evaluator, walk_min
from eilat.model import bus_share
from eilat.network import Pattern, fleet

LAT0, LON0 = 29.55, 34.95
DLON = 400 / (111_320 * math.cos(math.radians(29.55)))   # ~400 m east per step


def stops():
    return pd.DataFrame({"stop_id": [1, 2, 3, 4], "stop_lat": [LAT0] * 4,
                         "stop_lon": [LON0 + i * DLON for i in range(4)]})


def points():
    return pd.DataFrame({"lat": [LAT0 + 0.0003, LAT0 + 0.0003, LAT0 + 0.0003],
                         "lon": [LON0, LON0 + 3 * DLON, LON0 + 0.5 * DLON]})


def line(name, stops_, headway, seg=2.0):
    return Pattern(name=name, line=name.split("/")[0], stops=list(stops_),
                   seg_min={p: [seg] * (len(stops_) - 1) for p in P.PERIODS},
                   headway={p: headway for p in P.PERIODS})


def test_walk_minutes():
    m = walk_min(LAT0, LON0, LAT0, LON0 + DLON)
    assert m == pytest.approx(400 * P.DETOUR / (P.WALK_KMH * 1000 / 60), rel=0.01)


def test_single_ride_cost_is_walk_wait_ride_without_transfer_penalty():
    ev = Evaluator(stops(), points())
    r = ev.run([line("X/0", [1, 2, 3, 4], 20.0)], "09-12", sources=[0])
    access = ev.acc[0, 0] * P.W_WALK; egress = ev.acc[1, 3] * P.W_WALK
    expected = access + P.W_WAIT * 10 + 6.0 + egress      # wait = headway / 2; three segments of 2 min
    assert r["gc_bus"][0, 1] == pytest.approx(expected, rel=1e-6)


def test_every_bus_path_contains_a_ride():
    """The bug fixed: walk to a stop and straight on to the destination must not count as a bus trip."""
    ev = Evaluator(stops(), points())
    r = ev.run([], "09-12", sources=[0])           # no lines at all
    assert not np.isfinite(r["gc_bus"][0, 2])     # the nearby point is reachable only on foot
    assert r["walk"][0, 2] > 0


def test_common_lines_combine_frequency_and_split_riders():
    ev = Evaluator(stops(), points())
    one = ev.run([line("X/0", [1, 2, 3, 4], 20.0)], "09-12", sources=[0])
    two = ev.run([line("X/0", [1, 2, 3, 4], 20.0), line("Y/0", [1, 2, 3, 4], 20.0)], "09-12", sources=[0])
    # two lines every 20 min = one every 10 min: the wait halves
    assert one["gc_bus"][0, 1] - two["gc_bus"][0, 1] == pytest.approx(P.W_WAIT * 5, rel=1e-6)
    trips = np.zeros((1, 3)); trips[0, 1] = 100
    by_pat, _ = Evaluator.boardings(two, trips, 2)
    assert by_pat == pytest.approx([50, 50])


def test_loads_follow_the_ride():
    ev = Evaluator(stops(), points())
    pats = [line("X/0", [1, 2, 3, 4], 20.0)]
    r = ev.run(pats, "09-12", sources=[0])
    trips = np.zeros((1, 3)); trips[0, 1] = 30
    loads = [np.zeros(3)]
    Evaluator.boardings(r, trips, 1, loads=loads)
    assert loads[0] == pytest.approx([30, 30, 30])


def test_skipping_a_stop_saves_stop_cost_times_chance_of_stopping():
    p = line("X/0", [1, 2, 3, 4], 20.0)
    base = p.run_min("09-12")
    p.skip = {2}; p.p_served = {2: 0.5}
    assert base - p.run_min("09-12") == pytest.approx(P.STOP_COST_S / 60 * 0.5)


def test_fleet_counts_run_plus_layover_over_headway():
    p = line("X/0", [1, 2, 3, 4], 15.0, seg=5.0)        # 15 min run, layover max(1.5, 5) = 5 min
    buses, hours = fleet([p])
    assert all(b == math.ceil(20 / 15) for b in buses.values())
    assert hours == pytest.approx(20 / 15 * sum(b - a for a, b in P.PERIODS.values()))


def test_bus_share_rises_when_the_bus_gets_faster():
    walk = np.array([30.0])
    assert bus_share(np.array([10.0]), walk, 0.3, 0.0)[0] > bus_share(np.array([25.0]), walk, 0.3, 0.0)[0]
