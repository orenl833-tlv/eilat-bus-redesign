"""Check networks found by scripts/optimize_tt.py on leaving times and delay draws the search did not see.

For today's real timetable, the current recommended plan and each given state file: mean door-to-door minutes
(06:00-22:59, SEEDS new delay draws, other random leaving times), the worst area against today, perceived
minutes (07-21, walk and wait x1.6, +5 a transfer), buses (vehicle blocks, no recovery), bus-hours, and the
lines that run.

Usage: PYTHONPATH=.:scripts:analysis python3 scripts/check_tt.py data/opt_tt_today_s1.json [more states]
Output: data/check_tt.json
"""
import json
import math
import sys

import optimize_tt as X
import timetable_offsets as T
from eilat import network as EN

SEEDS, P_SEEDS = range(700, 710), range(800, 803)


class PatsNet(T.Base):
    """A fixed pattern list as a Base network (for perceived time and buses)."""

    def __init__(self, tt, pats):
        self.__dict__.update({k: v for k, v in tt.__dict__.items() if k != "_memo"})
        self._memo = {}
        self.pats = pats
        self.start = {}

    def network(self, phases):
        return X.TT.net_of(self, self.pats)


def load(S, path):
    st = dict(S.prob.state0)
    for k, v in json.load(open(path)).items():
        if k in st:
            st[k] = {q: (h if h is not None else math.inf) for q, h in v.items()}
    return st


def main():
    S = X.Search()
    today = T.TodayNet(); today.foot = S.tt.foot
    rows = {}
    thb, (tm, tp) = S.tt.per_home(today.network(today.start), "holdout", SEEDS, metric="both")
    th = {o: v[0] for o, v in thb.items()}
    rows["today"] = dict(minutes=tm, perceived_trips=tp, perceived=today.perceived(today.start, T.HOLDOUT_LEAVE, P_SEEDS),
                         buses=today.buses(today.start), worst_area=1.0)
    for path in ["data/opt_full_peak-3_warm.json"] + sys.argv[1:]:
        st = load(S, path)
        pats = S.prob.network(st)
        N = PatsNet(S.tt, pats)
        hb, (m, pm) = S.tt.per_home(N.network(None), "holdout", SEEDS, metric="both")
        h = {o: v[0] for o, v in hb.items()}
        _, hours = EN.fleet(pats)
        rows[path] = dict(minutes=m, vs_today=m / tm - 1, worst_area=max(h[o] / th[o] for o in h),
                          perceived_trips=pm, perceived_vs_today=pm / tp - 1,
                          worst_area_perceived=max(hb[o][1] / thb[o][1] for o in hb),
                          perceived=N.perceived(None, T.HOLDOUT_LEAVE, P_SEEDS), buses=N.buses(None), bus_hours=hours,
                          lines=sorted(k for k, v in st.items() if any(math.isfinite(x) for x in v.values())))
        print(path, {k: v for k, v in rows[path].items() if k != "lines"}, flush=True)
    rows["today"]["minutes_check"] = tm
    print("today", rows["today"], flush=True)
    json.dump(rows, open("data/check_tt.json", "w"), ensure_ascii=False, indent=1, default=float)


if __name__ == "__main__":
    main()
