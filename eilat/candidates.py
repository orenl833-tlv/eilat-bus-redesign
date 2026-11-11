"""Candidate lines for the redesign, all on streets and stops buses already use (stop_graph.csv).

- straightened(): a long line with its detours cut, where the stop graph has a path at least MIN_SAVE minutes
  faster between two of its stops; the stops it no longer passes are left to walking or other lines.
- skipping(): a line that passes its least used stops without stopping, where another of its stops is within
  SKIP_WALK_M; the time saved is STOP_COST_S x the chance the bus would have stopped there.
- new lines: shortest paths in the stop graph through a list of anchor stops (both directions).
Segment times: planned minutes on the graph x the SIRI correction of the lines that use the street.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra

from . import params as P
from .evaluate import walk_min
from .network import Pattern

# stops never skipped or cut: luggage (hotels, terminals, border crossings, airport), the hospital, malls
PROTECTED_RE = "בית חולים|יוספטל|מלון|תחנה מרכזית|חנה וסע|מעבר גבול|קניון|נמל תעופה|קמפוס"
MIN_SAVE = 3.0
MAX_SPAN = 10      # a detour cut spans at most this many stops
MIN_SAVE_SHARE = 0.3  # and saves at least this share of the stretch's time
SKIP_WALK_M = 350

ANCHORS = {  # stop_id: label (verified against the GTFS stop names)
    49835: "Old central station (Star Eilat)", 28805: "Hotels (Magic Palace / Crown Plaza)",
    29096: "Hotels (Herods / Dan)", 28809: "Ice Mall", 12719: "Big centre", 29085: "Yoseftal hospital",
    50069: "City entrance terminal", 12360: "Coral Beach", 29202: "Princess hotel (Taba)", 12356: "City hall",
    50286: "Depot",
}


class StopGraph:
    def __init__(self, base_patterns):
        g = pd.read_csv("data/stop_graph.csv")
        self.stops = pd.read_csv("data/stops_all.csv")
        self.ids = list(self.stops.stop_id); self.ix = {s: i for i, s in enumerate(self.ids)}
        g = g[g.u.isin(self.ix) & g.v.isin(self.ix)]
        self.edge_min = {(int(u), int(v)): float(m) for u, v, m in zip(g.u, g.v, g.minutes, strict=True)}
        n = len(self.ids)
        self.G = csr_matrix((g.minutes.values, (g.u.map(self.ix).values, g.v.map(self.ix).values)), shape=(n, n))
        # SIRI correction per street: median factor of the base lines using it, per period
        fac = pd.read_csv("data/runtime_factor.csv", dtype={"line": str})
        per_edge = {}
        for pt in base_patterns:
            ln = pt.line.replace("א", "")
            for p in P.PERIODS:
                f = fac[(fac.line == ln) & (fac.period == p)].factor
                if len(f):
                    for u, v in zip(pt.stops[:-1], pt.stops[1:], strict=True):
                        per_edge.setdefault((u, v, p), []).append(float(f.iloc[0]))
        self.efac = {k: float(np.median(v)) for k, v in per_edge.items()}
        self.pfac = fac.groupby("period").factor.median().to_dict()
        self.protected = set(self.stops[self.stops.stop_name.str.contains(PROTECTED_RE, na=False)].stop_id)

    def seg_minutes(self, stops):
        out = {}
        for p in P.PERIODS:
            seg = []
            for u, v in zip(stops[:-1], stops[1:], strict=True):
                m = self.edge_min.get((u, v))
                if m is None:  # not an existing edge: straight line at 20 km/h (should not happen for graph paths)
                    a, b = self.stops.iloc[self.ix[u]], self.stops.iloc[self.ix[v]]
                    m = walk_min(a.stop_lat, a.stop_lon, b.stop_lat, b.stop_lon) / P.DETOUR * P.WALK_KMH / 20
                seg.append(m * self.efac.get((u, v, p), self.pfac.get(p, 1.25)))
            out[p] = seg
        return out

    def path(self, u, v):
        if u not in self.ix or v not in self.ix:
            return None
        d, pred = dijkstra(self.G, directed=True, indices=self.ix[u], return_predecessors=True)
        if not math.isfinite(d[self.ix[v]]):
            return None
        out, x = [], self.ix[v]
        while x != self.ix[u]:
            out.append(self.ids[x]); x = pred[x]
        return [u] + out[::-1]

    def through(self, anchors):
        full = [anchors[0]]
        for a, b in zip(anchors[:-1], anchors[1:], strict=True):
            p = self.path(a, b)
            if p is None:
                return None
            full += p[1:]
        return full


def make(sg, name, line, stops, headway=None):
    hw = headway or {p: 20.0 for p in P.PERIODS}
    return Pattern(name=name, line=line, stops=list(stops), seg_min=sg.seg_minutes(stops), headway=dict(hw))


def straightened(sg, pt):
    """Cut detours: replace stops[i..j] by the graph's fastest path when it saves >= MIN_SAVE minutes."""
    stops = list(pt.stops); seg = pt.seg_min["09-12"]
    cum = np.concatenate([[0], np.cumsum(seg)])
    best = []
    for i in range(len(stops) - 3):
        d, pred = dijkstra(sg.G, directed=True, indices=sg.ix.get(stops[i], 0), return_predecessors=True) \
            if stops[i] in sg.ix else (None, None)
        if d is None:
            continue
        for j in range(i + 3, min(i + MAX_SPAN + 1, len(stops))):
            if stops[j] not in sg.ix or stops[j] == stops[i]:
                continue
            sp = d[sg.ix[stops[j]]] * sg.pfac.get("09-12", 1.25)
            save = (cum[j] - cum[i]) - sp
            if any(x in sg.protected for x in stops[i + 1:j]):
                continue
            if math.isfinite(sp) and save >= MIN_SAVE and save >= MIN_SAVE_SHARE * (cum[j] - cum[i]):
                best.append((save, i, j))
    best.sort(reverse=True)
    used, cuts = set(), []
    for save, i, j in best:
        if not used.intersection(range(i, j + 1)):
            cuts.append((i, j)); used.update(range(i, j + 1))
    if not cuts:
        return None
    new = []; k = 0
    for i, j in sorted(cuts):
        new += stops[k:i]
        new += sg.path(stops[i], stops[j])[:-1]
        k = j
    new += stops[k:]
    return make(sg, pt.name + "s", pt.line + "s", new, pt.headway)


def skipping(sg, pt, stop_use, trips_per_day):
    """Pass the least used stops without stopping, if another stop of the line is within SKIP_WALK_M."""
    lat = dict(zip(sg.stops.stop_id, sg.stops.stop_lat, strict=True)); lon = dict(zip(sg.stops.stop_id, sg.stops.stop_lon, strict=True))
    use = np.array([stop_use.get(s, 0.0) for s in pt.stops])
    cut = np.quantile(use[1:-1], 0.3) if len(use) > 4 else -1
    skip, p_served = set(), {}
    for i, s in enumerate(pt.stops[1:-1], start=1):
        per_trip = use[i] / max(trips_per_day, 1)
        p_served[s] = 1 - math.exp(-per_trip)
        if use[i] <= cut and s not in sg.protected:
            near = [t for t in pt.stops if t != s and t not in skip and t in lat and s in lat and
                    walk_min(lat[s], lon[s], lat[t], lon[t]) * (P.WALK_KMH * 1000 / 60) <= SKIP_WALK_M * P.DETOUR]
            if near:
                skip.add(s)
    if not skip:
        return None
    q = make(sg, pt.name + "x", pt.line + "x", pt.stops, pt.headway)
    q.seg_min = pt.seg_min; q.skip = skip; q.p_served = p_served
    return q


def new_lines(sg, area_anchor):
    """Direct lines from neighbourhood anchors to the main attractors, both directions."""
    S = 49835; H = 28805; BIG = 12719; HOSP = 29085; ENT = 50069; CORAL = 12360; TABA = 29202
    specs = {"SC1": [S, H, CORAL, TABA], "SC2": [BIG, S, H, CORAL, TABA]}
    for a, st in area_anchor.items():
        specs[f"A{a}H"] = [st, S, H]
        specs[f"A{a}B"] = [st, HOSP, S, BIG]
        specs[f"A{a}E"] = [st, S, H, ENT]
    out = []
    for name, anchors in specs.items():
        f = sg.through(anchors); b = sg.through(anchors[::-1])
        if f is None or b is None or len(f) < 4:
            continue
        out.append([make(sg, f"{name}/0", name, f), make(sg, f"{name}/1", name, b)])
    return out


def designed_lines(sg, area_anchor, via=(49835, 12719), min_stops=6, min_run=8.0, overlap=0.8):
    """Two-way lines designed from scratch: for every pair of endpoints (neighbourhood anchors and the main
    places in ANCHORS), the fastest path along streets buses drive today, each way (stops on the two sides of a
    street differ, so the two directions are separate paths); and the same through one hub (old central
    station, big centre) when that adds at most 25% to the time. Near-duplicates (stop sets overlapping more
    than `overlap`) keep the faster. Returns [[pattern/0, pattern/1], ...] named D<a>_<b> or D<a>_<b>v<hub>."""
    ends = sorted(set(area_anchor.values()) | set(ANCHORS))
    ends = [e for e in ends if e in sg.ix]

    def run(stops):
        return sum(sg.edge_min.get((u, v), 1.0) for u, v in zip(stops[:-1], stops[1:], strict=True))

    found = []
    for i, a in enumerate(ends):
        for b in ends[i + 1:]:
            f, r = sg.path(a, b), sg.path(b, a)
            if f is None or r is None or len(f) < min_stops or run(f) < min_run:
                continue
            found.append((f"D{a}_{b}", f, r, run(f) + run(r)))
            for h in via:
                if h in (a, b):
                    continue
                fv, rv = sg.through([a, h, b]), sg.through([b, h, a])
                if fv is None or rv is None:
                    continue
                t = run(fv) + run(rv)
                if t <= 1.25 * (run(f) + run(r)):
                    found.append((f"D{a}_{b}v{h}", fv, rv, t))
    found.sort(key=lambda x: x[3])
    kept, sets = [], []
    for name, f, r, t in found:
        s = set(f) | set(r)
        if any(len(s & o) / len(s | o) > overlap for o in sets):
            continue
        kept.append([make(sg, f"{name}/0", name, f), make(sg, f"{name}/1", name, r)]); sets.append(s)
    return kept
