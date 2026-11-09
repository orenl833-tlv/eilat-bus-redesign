"""Perceived door-to-door time ("generalised cost", in in-vehicle minutes) on any network, frequency based,
with common lines.

The graph has stop nodes and point nodes only. A "ride leg" edge joins any two stops i -> j that some line
serves in that order (both stops served, not skipped). Where several lines serve the same i -> j, the
passenger boards the first attractive one: lines whose ride time is within COMMON_SLACK minutes of the
fastest are attractive; the wait is half their combined headway; riders split by frequency.
Edge cost = W_WAIT x wait + average ride time + TRANSFER_PENALTY (one penalty taken back at the end, so a trip
with k legs pays k-1). Walking: point -> stop, stop -> point, stop <-> stop transfers. Walking all the way is
the separate alternative.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra

from . import params as P

MX, MY = 111_320 * np.cos(np.radians(29.55)), 110_850
COMMON_SLACK = 5.0   # minutes: a slower line still counts as attractive within this margin (assumption)


def walk_min(lat1, lon1, lat2, lon2):
    d = np.hypot((np.asarray(lon1) - lon2) * MX, (np.asarray(lat1) - lat2) * MY) * P.DETOUR
    return d / (P.WALK_KMH * 1000 / 60)


class Evaluator:
    def __init__(self, stops: pd.DataFrame, points: pd.DataFrame):
        self.stops = stops.reset_index(drop=True)
        self.sid = {s: i for i, s in enumerate(self.stops.stop_id)}
        self.points = points.reset_index(drop=True)
        s_lat, s_lon = self.stops.stop_lat.values, self.stops.stop_lon.values
        p_lat, p_lon = self.points.lat.values, self.points.lon.values
        self.acc = walk_min(p_lat[:, None], p_lon[:, None], s_lat[None, :], s_lon[None, :])
        self.tr = walk_min(s_lat[:, None], s_lon[:, None], s_lat[None, :], s_lon[None, :])
        self.direct = walk_min(p_lat[:, None], p_lon[:, None], p_lat[None, :], p_lon[None, :])
        self.wmax = P.WALK_MAX_M * P.DETOUR / (P.WALK_KMH * 1000 / 60)
        self.tmax = P.TRANSFER_WALK_M * P.DETOUR / (P.WALK_KMH * 1000 / 60)

    def legs(self, pats, period):
        """All ride legs i -> j with their attractive lines. Returns DataFrame u, v, cost_parts, lines."""
        rows = []
        for k, pt in enumerate(pats):
            h = pt.headway.get(period, math.inf)
            if not math.isfinite(h):
                continue
            seg = np.asarray(pt.times(period))
            cum = np.concatenate([[0], np.cumsum(seg)])
            idx = [i for i, s in enumerate(pt.stops) if s in self.sid and s not in pt.skip]
            if len(idx) < 2:
                continue
            ii = np.array(idx)
            a, b = np.triu_indices(len(ii), 1)
            ia, ib = ii[a], ii[b]
            u = np.array([self.sid[pt.stops[x]] for x in ia]); v = np.array([self.sid[pt.stops[x]] for x in ib])
            ok = u != v
            rows.append(pd.DataFrame({"u": u[ok], "v": v[ok], "ivt": (cum[ib] - cum[ia])[ok], "f": 1 / h, "k": k}))
        if not rows:
            return pd.DataFrame(columns=["u", "v", "ivt", "f", "k"])
        L = pd.concat(rows)
        # a line serving i->j twice (loops) keeps its fastest ride
        L = L.sort_values("ivt").drop_duplicates(["u", "v", "k"])
        L["best"] = L.groupby(["u", "v"]).ivt.transform("min")
        L = L[L.ivt <= L.best + COMMON_SLACK]
        return L

    def run(self, pats, period, w_walk=P.W_WALK, sources=None, transfer_penalty=P.TRANSFER_PENALTY):
        ns, npt = len(self.stops), len(self.points)
        L = self.legs(pats, period)
        g = L.groupby(["u", "v"])
        F = g.f.sum()
        ivt = (L.ivt * L.f).groupby([L.u, L.v]).sum() / F
        leg_cost = (P.W_WAIT * 0.5 / F + ivt * P.W_INVEHICLE + transfer_penalty)
        e = [pd.DataFrame({"u": leg_cost.index.get_level_values(0), "v": leg_cost.index.get_level_values(1),
                           "w": leg_cost.values, "t": 1})]
        a, b = np.nonzero((self.tr <= self.tmax) & (self.tr > 0))
        e.append(pd.DataFrame({"u": a, "v": b, "w": self.tr[a, b] * w_walk, "t": 0}))
        pi, si = np.nonzero(self.acc <= self.wmax)
        e.append(pd.DataFrame({"u": ns + pi, "v": si, "w": self.acc[pi, si] * w_walk, "t": 2}))
        e.append(pd.DataFrame({"u": si, "v": ns + npt + pi, "w": self.acc[pi, si] * w_walk, "t": 3}))
        E = pd.concat(e).sort_values("w").drop_duplicates(["u", "v"])
        n = ns + 2 * npt
        G = csr_matrix((E.w.values, (E.u.values, E.v.values)), shape=(n, n))
        src = np.arange(npt) if sources is None else np.asarray(sources)
        dist, pred = dijkstra(G, directed=True, indices=ns + src, return_predecessors=True)
        gc = dist[:, ns + npt: ns + 2 * npt] - transfer_penalty
        leg_type = {(int(u), int(v)): int(t) for u, v, t in zip(E.u.values, E.v.values, E.t.values, strict=True)}
        return dict(gc_bus=gc, walk=self.direct[src] * w_walk, pred=pred, ns=ns, npt=npt, legs=L,
                    leg_type=leg_type, src=src)

    @staticmethod
    def boardings(res, od_trips, n_pats):
        """Bus trips on the best paths -> boardings per pattern (split by frequency on common legs) and
        boardings+alightings per stop. od_trips: (len(src) x npt) array."""
        ns, npt, pred, lt = res["ns"], res["npt"], res["pred"], res["leg_type"]
        share = res.get("_share")
        if share is None:
            L = res["legs"]
            L = L.assign(sh=L.f / L.groupby(["u", "v"]).f.transform("sum"))
            share = {}
            for (u, v), grp in L.groupby(["u", "v"]):
                share[(int(u), int(v))] = list(zip(grp.k.values, grp.sh.values, strict=True))
            res["_share"] = share
        by_pat = np.zeros(n_pats); by_stop = {}
        srcs, dsts = np.nonzero(od_trips > 0)
        for i, j in zip(srcs, dsts, strict=True):
            node = ns + npt + j; q = od_trips[i, j]; guard = 0
            while guard < 200:
                guard += 1
                p = pred[i, node]
                if p < 0:
                    break
                if lt.get((int(p), int(node))) == 1:
                    for k, s in share[(int(p), int(node))]:
                        by_pat[k] += q * s
                    by_stop[int(p)] = by_stop.get(int(p), 0) + q
                    by_stop[int(node)] = by_stop.get(int(node), 0) + q
                node = p
        return by_pat, by_stop
