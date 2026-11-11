"""What a bus lane on Sderot HaTmarim would give, for today's network and the recommended one (net_F2).

Lane segments: every segment between two stops on Sderot HaTmarim, and from it to Derech HaArava, both
directions (the most congestion-delayed segments in data/segment_congestion.csv). With the lane:
- speed: each lane segment runs at every hour in its free-flow time (the fastest of its 05-06 and 22-23
  medians, as measured by GPS);
- reliability: on lane segments a ride's run-time deviation is scaled by LANE_VAR = the steadiest busy segments'
  spread (IQR / median) over the lane segments' own spread today.
Scored as the validation (scripts/check_tt.py, analysis/committed_rider.py): demand-weighted door-to-door minutes on
unseen leaving times and delay draws (winter), and the residents' trips for a clairvoyant and a committed rider.

Usage: MODE=design OD=demand PYTHONPATH=.:scripts:analysis python3 analysis/bus_lane.py   Output: data/bus_lane.json
"""
import json

import pandas as pd

import check_tt as C
import optimize_tt as X
import timetable_offsets as T
from eilat.speeds import Speeds

SEEDS = range(1700, 1706)


def lane_segments():
    S = pd.read_csv("data/segment_times.csv")
    st = pd.read_csv("data/stops_all.csv").drop_duplicates("stop_id").set_index("stop_id").stop_name
    nm = lambda x: str(st.get(x, ""))  # noqa: E731
    pairs = S[["a", "b"]].drop_duplicates()
    lane = {(int(a), int(b)) for a, b in zip(pairs.a, pairs.b, strict=True)
            if ("התמרים" in nm(a) and "התמרים" in nm(b)) or ("התמרים" in nm(a) and "דרך הערבה" in nm(b))
            or ("דרך הערבה" in nm(a) and "התמרים" in nm(b))}
    free = {}
    for (a, b), g in S[S.set_index(["a", "b"]).index.isin(lane)].groupby(["a", "b"]):
        q = g[g.hour.isin([5, 6, 22, 23])]
        free[(int(a), int(b))] = float((q if len(q) else g)["median"].min())
    C2 = pd.read_csv("data/segment_congestion.csv")
    busy = C2[C2.passes_day >= 20]
    lane_iqr = C2[C2.set_index(["a", "b"]).index.isin(lane)].iqr.median()
    var = float(busy.iqr.nsmallest(6).median() / lane_iqr)
    return lane, free, var


class LaneSpeeds(Speeds):
    def __init__(self, free):
        super().__init__()
        self.free = free

    def minutes(self, a, b, clock, default=None):
        if (a, b) in self.free:
            return self.free[(a, b)]
        return super().minutes(a, b, clock, default)


def evaluate(S, lane_on, lane, free, var, path):
    T.SPEEDS = LaneSpeeds(free) if lane_on else Speeds()
    today = T.TodayNet(); today.foot = S.tt.foot
    nets = {"today": today.network(today.start), "net_F2": C.PatsNet(S.tt, S.prob.network(C.load(S, path))).network(None)}
    out = {}
    for k, (net, keys) in nets.items():
        if lane_on:
            net.lane, net.lane_var = lane, var
        _, m = S.tt.per_home((net, keys), "holdout", SEEDS)
        clair = comm = w = 0.0
        reals = [net.realize(S.tt.sampler, s, keys) for s in SEEDS[:3]]
        for o, d, wt, wd in S.tt.od:
            for t0 in T.leave_times(o, "holdout")[::4]:
                for real in reals:
                    r = real.plan(o[0], o[1], d[0], d[1], t0, T.TRANSFER_MIN)
                    a = wd if r is None else min(r["arrive"] - t0, wd)
                    c = real.committed(net, o[0], o[1], d[0], d[1], t0, T.TRANSFER_MIN)
                    b = wd if c is None else min(c - t0, wd)
                    clair += wt * a; comm += wt * b; w += wt
        out[k] = dict(demand_minutes=round(m, 2), clairvoyant=round(clair / w, 2), committed=round(comm / w, 2))
        print("lane" if lane_on else "no lane", k, out[k], flush=True)
    return out


def main():
    lane, free, var = lane_segments()
    print(f"{len(lane)} lane segments; reliability factor {var:.2f}", flush=True)
    S = X.Search()
    res = {"segments": len(lane), "lane_var": round(var, 2),
           "no_lane": evaluate(S, False, lane, free, var, "data/net_F2.json"),
           "lane": evaluate(S, True, lane, free, var, "data/net_F2.json")}
    json.dump(res, open("data/bus_lane.json", "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
