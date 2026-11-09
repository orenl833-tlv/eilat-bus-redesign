"""Demand on a network: bus trips by purpose and period, boardings per line, and the perceived-time objective."""
from __future__ import annotations

import numpy as np

from . import demand as D
from . import params as P
from .evaluate import Evaluator


def hot_midday(season, period):
    return P.SEASONS[season]["hot"] and period == "12-15"


def bus_share(gc_bus, walk, lam, const):
    """Logit share of the bus against walking (both perceived minutes)."""
    x = np.clip(lam * (walk - gc_bus) + const, -30, 30)
    return 1 / (1 + np.exp(-x))


class Model:
    def __init__(self, n_points=6):
        import pandas as pd
        self.areas, self.pts = D.points()
        stops = pd.read_csv("data/stops_all.csv")
        self.ev = Evaluator(stops, self.pts)
        self.homes = np.where(self.pts.kind == "home")[0]
        self.att = np.where(self.pts.kind == "attractor")[0]

    def run(self, pats, season, K=None, lam=P.LOGIT_SCALE, const=P.BUS_CONSTANT, car_prop=P.CAR_PROPENSITY,
            track=True, walk_heat=P.W_WALK_HEAT, transfer_penalty=P.TRANSFER_PENALTY):
        """Returns per-purpose boardings per pattern (if track), bus trips, and the objective pieces."""
        K = K or {p: 1.0 for p in D.PURPOSES}
        pot, prop, tour, hotel = D.potential(self.pts, season, car_prop=car_prop)
        res = {"board": {p: np.zeros(len(pats)) for p in D.PURPOSES}, "trips": {p: 0.0 for p in D.PURPOSES},
               "stop_use": {}, "cost": 0.0, "potential": 0.0,
               "cost_p": {p: 0.0 for p in D.PURPOSES},
               "home_cost": {p: np.zeros(len(self.homes)) for p in D.PURPOSES},
               "home_trips": {p: np.zeros(len(self.homes)) for p in D.PURPOSES}}
        nocar = self.pts.nocar.values[self.homes]
        eq = (P.NOCAR_EQUITY_WEIGHT * nocar + car_prop * (1 - nocar)) / (nocar + car_prop * (1 - nocar))
        hotel_pt = self.att[hotel]
        for k, period in enumerate(P.PERIODS):
            ww = walk_heat if hot_midday(season, period) else P.W_WALK
            out = self.ev.run(pats, period, w_walk=ww, sources=self.homes, transfer_penalty=transfer_penalty)
            back = self.ev.run(pats, period, w_walk=ww, sources=self.att, transfer_penalty=transfer_penalty)
            for p in D.PURPOSES:
                if p == "tourist":
                    hrow = hotel  # row of the hotel point among the attractor sources
                    gb, wk = back["gc_bus"], back["walk"]
                    sets = [(D.PROFILE[p]["out"][k] * tour[None, :] * K[p], gb[[hrow]][:, self.att],
                             wk[[hrow]][:, self.att], "back", [hrow], self.att),
                            (D.PROFILE[p]["back"][k] * tour[:, None] * K[p], gb[:, [hotel_pt]], wk[:, [hotel_pt]],
                             "back", list(range(len(self.att))), [hotel_pt])]
                else:
                    pot_p = pot[p] * K[p]
                    sets = [(D.PROFILE[p]["out"][k] * pot_p * prop[:, None], out["gc_bus"][:, self.att],
                             out["walk"][:, self.att], "out", list(range(len(self.homes))), self.att),
                            (D.PROFILE[p]["back"][k] * pot_p.T * prop[None, :], back["gc_bus"][:, self.homes],
                             back["walk"][:, self.homes], "back", list(range(len(self.att))), self.homes)]
                for trips, gcb, wk, which, rows_, cols_ in sets:
                    if trips.sum() <= 0:
                        continue
                    sh = bus_share(gcb, wk, lam, const)
                    bus = trips * sh
                    res["trips"][p] += bus.sum()
                    res["potential"] += trips.sum()
                    # objective: expected perceived minutes (logsum) over all potential travellers of the bus market
                    ls = -np.logaddexp(-lam * gcb + const, -lam * wk) / lam
                    tl = trips * ls
                    res["cost"] += float(tl.sum())
                    if p == "tourist":
                        res["cost_p"][p] += float(tl.sum())
                    elif which == "out":   # rows are homes
                        res["cost_p"][p] += float((tl * eq[:, None]).sum())
                        res["home_cost"][p] += tl.sum(axis=1); res["home_trips"][p] += trips.sum(axis=1)
                    else:                  # columns are homes
                        res["cost_p"][p] += float((tl * eq[None, :]).sum())
                        res["home_cost"][p] += tl.sum(axis=0); res["home_trips"][p] += trips.sum(axis=0)
                    if track:
                        r = out if which == "out" else back
                        full = np.zeros((len(rows_), self.ev.points.shape[0]))
                        full[:, cols_] = bus
                        sub = dict(r); sub["pred"] = r["pred"][rows_]
                        if "_share" in r:
                            sub["_share"] = r["_share"]
                        bp, bs = Evaluator.boardings(sub, full, len(pats))
                        r["_share"] = sub["_share"]
                        res["board"][p] += bp
                        for s, q in bs.items():
                            res["stop_use"][s] = res["stop_use"].get(s, 0) + q
        return res


def line_of(pattern_line):
    """Map a pattern's line to the ridership file's line number (variants merged)."""
    s = str(pattern_line).replace("א", "")
    return "schools" if s in ("80", "81", "82") else s
