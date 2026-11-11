"""Buses and drivers for a timetable-searched network against today, with terminal recovery (winter weekday).

Both timetables are timed the same way (street segments at the GPS-measured time of their hour and direction,
eilat/speeds.py): today's printed departures, and the network's departures every headway (evening to 23:00).
Vehicle blocks (scripts/blocking.py) with recovery at each terminal = share x the trip's run time (at least
the layover minimum); then driver duties under the rest rules (scripts/shifts.py), standard and with overtime.
School lines keep today's trips in both.

Usage: PYTHONPATH=.:scripts:analysis python3 analysis/fleet_tt.py data/net_H.json   Output: data/fleet_tt.json
"""
import json
import sys

import pandas as pd

import blocking as BL
import check_tt as C
import optimize_tt as X
import shifts as SH
import timetable_offsets as T

RECOVERY = (0.0, 0.10, 0.15)


def trips_of(net, stops):
    t = pd.DataFrame([dict(line=net.line.get(tid, ""), start=tt[0], end=tt[-1], o=int(s[0]), d=int(s[-1]))
                      for tid, (s, tt) in net.trips.items()])
    return t[t.o.isin(stops.index) & t.d.isin(stops.index)]


def main():
    path = sys.argv[1]
    S = X.Search()
    today = T.TodayNet(); today.foot = S.tt.foot
    nets = {"today": today.network(today.start)[0],
            path: C.PatsNet(S.tt, S.prob.network(C.load(S, path))).network(None)[0]}
    out = {}
    for name, net in nets.items():
        trips = trips_of(net, S.tt.stops)
        for rec in RECOVERY:
            B, _, blocks = BL.block(trips, S.tt.stops, recovery=rec)
            row = dict(buses=len(blocks), bus_hours=round(float(B.hours_out.sum()), 1))
            for sc, dmax in SH.SCENARIOS.items():
                r = SH.staff([p for b in blocks for p in SH.pieces(b, dmax)])
                row[f"duties_{sc}"] = int(r["duties"])
                row[f"drivers_{sc}"] = int(round(r["duties"] * SH.ROSTER_FACTOR))   # rest days, holidays, sickness
                row[f"driver_cost_day_{sc}"] = int(r["cost_day"])
            out[f"{name}@{rec}"] = row
            print(name, rec, row, flush=True)
    json.dump(out, open("data/fleet_tt.json", "w"), indent=1)


if __name__ == "__main__":
    main()
