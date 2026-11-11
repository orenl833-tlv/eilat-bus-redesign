"""A pulse network with several hubs (the Swiss "Taktknoten" idea): every hub pulses every PULSE minutes, each at
its own phase, and a line passing several hubs is timed to meet each of them.

- The units are the pool's lines (today's lines, their variants, new lines: scripts/optimize.py MODE=design). A
  line pattern passing within 300 m of one or more hubs is cut at each of them into pieces; a line that passes no
  hub runs as an ordinary line (every h minutes).
- Timing, along each pattern: the piece reaching the first hub arrives ARRIVE_BEFORE before one of its pulses; each
  piece leaving a hub leaves DEPART_AFTER after a pulse; a piece running hub to hub leaves at a pulse of the first
  and waits, if early, for the next pulse of the second (the phases are set so the main trunk, city hall - other
  hub, fits: phase = city hall's + the midday run + ARRIVE_BEFORE + DEPART_AFTER, modulo PULSE).
- Holding: a piece leaving a hub waits for the latest piece arriving at that hub in the same pulse (+ the transfer
  time), at most HOLD_MAX; and never leaves before its own bus has arrived (+ the transfer time).
- A line runs every pulse (PULSE) or every other (2 x PULSE), by day and evening, or not; scored as
  scripts/optimize_tt.py and analysis/pulse.py (same budget and rules).

Usage: MODE=design OD=demand FREQ_RULE=1 PULSE=15 PYTHONPATH=.:scripts:analysis python3 analysis/pulse_multi.py SET ITERS SEED
  SET: a key of HUB_SETS.   Output: data/pulsem_<set>_p<pulse>_s<seed>.json (+ _ckpt.json)
"""
import json
import math
import os
import random
import sys
import time

import numpy as np
import pandas as pd

import optimize_tt as X
from eilat import network as EN
from eilat import params as P
from eilat.evaluate import walk_min
from eilat.speeds import Speeds
from eilat.timetable import Network, delay_key

HUB_STOPS = {"city_hall": [12356, 12625], "big_centre": [12719], "entrance": [50069], "hotels": [28805, 29096],
             "central_station": [49835]}
HUB_SETS = {"hall_big": ["city_hall", "big_centre"], "hall_entrance": ["city_hall", "entrance"],
            "hall_big_hotels": ["city_hall", "big_centre", "hotels"], "hall": ["city_hall"]}
PULSE = int(os.environ.get("PULSE", "15"))
ARRIVE_BEFORE, DEPART_AFTER, HOLD_MAX = 2.0, 3.0, 5.0
FIRST, LAST = 6 * 60, 23 * 60
T0 = 0.004
SPEEDS = Speeds()
MAX_M = 300.0


class MultiPulseNet(Network):
    def realize(self, sampler, seed, keys=None, dkey=None):
        real = super().realize(sampler, seed, keys, dkey)
        arr_end = {t: real.realized_times(t)[1][-1] for t in self.chain_prev.values() if t in real.trips}
        for (hub, pt), (inbound, outbound) in self.pulses.items():
            arr = [real.realized_times(t)[1][-1] for t in inbound if t in real.trips]
            latest = max(arr) if arr else -1e9
            for t in outbound:
                if t not in real.trips:
                    continue
                sched = self.trips[t][1][0]
                hold = min(max(0.0, latest + X.T.TRANSFER_MIN - sched), HOLD_MAX)
                prev = self.chain_prev.get(t)
                if prev is not None and prev in arr_end:      # its own bus must be in
                    hold = max(hold, arr_end[prev] + X.T.TRANSFER_MIN - sched)
                real.delays[t] = (hold, real.delays[t][1])
            # a piece's own arrival may itself have been held: recompute in order (pieces are listed by time)
        real._build(real.delays)
        return real


class Multi:
    def __init__(self, hub_set):
        self.S = X.Search()
        self.tt = self.S.tt
        prob = self.S.prob
        self.hubs = HUB_SETS[hub_set]
        st = prob.sg.stops.set_index("stop_id")
        self.hub_xy = {h: [(float(st.stop_lat[s]), float(st.stop_lon[s])) for s in HUB_STOPS[h]] for h in self.hubs}
        # phases: city hall 0; another hub = run city hall -> hub at midday + ARRIVE_BEFORE + DEPART_AFTER (mod PULSE)
        self.phase = {}
        for h in self.hubs:
            if h == self.hubs[0]:
                self.phase[h] = 0.0
                continue
            p = prob.sg.path(HUB_STOPS[self.hubs[0]][0], HUB_STOPS[h][0])
            run = SPEEDS.run(p, 12 * 60, lambda i, c, p=p: prob.sg.edge_min.get((p[i], p[i + 1]), 1.0) * SPEEDS.city_factor(c))
            self.phase[h] = float((run[-1] - 12 * 60 + ARRIVE_BEFORE + DEPART_AFTER) % PULSE)
        self.lines = {}            # name -> list of (pattern, [(stop index, hub)])
        for ln, pats in prob.lines.items():
            cuts = [self.cuts(p) for p in pats]
            self.lines[("M" if any(cuts) else "R") + ln] = list(zip(pats, cuts, strict=True))
        self.names = sorted(self.lines)
        base = {p.line for p in prob.base if p.line not in X.O.SCHOOL}
        self.base_lines = [n for n in self.names if n[1:] in base]
        self.memo = {}
        print(f"hubs {self.hubs}, phases {self.phase}, pulse {PULSE}: {sum(n[0] == 'M' for n in self.names)} pulse lines, "
              f"{sum(n[0] == 'R' for n in self.names)} ordinary", flush=True)

    def cuts(self, p):
        st = self.S.prob.sg.stops.set_index("stop_id")
        out = []
        for h in self.hubs:
            d = [min(walk_min(st.stop_lat[s], st.stop_lon[s], a, b) for a, b in self.hub_xy[h]) * P.WALK_KMH * 1000 / 60 for s in p.stops]
            j = int(np.argmin(d))
            if d[j] <= MAX_M and 0 < j < len(p.stops) - 1:
                out.append((j, h))
        out.sort()
        # a hub reached twice in a row (loops) or two hubs on the same stop: keep the first
        return [c for k, c in enumerate(out) if k == 0 or c[0] > out[k - 1][0]]

    def next_pulse(self, hub, t):
        """The first pulse of `hub` at or after t."""
        ph = self.phase[hub]
        return ph + math.ceil((t - ph) / PULSE - 1e-9) * PULSE

    def patterns(self, state):
        pats = list(self.S.prob.fixed)
        for n, (hd, he) in state.items():
            if hd is None and he is None:
                continue
            hw = {q: (he if q == "19-24" else hd) or math.inf for q in P.PERIODS}
            for p, _ in self.lines[n]:
                pats.append(EN.Pattern(name=p.name, line=p.line, stops=p.stops, seg_min=p.seg_min, headway=dict(hw),
                                       skip=p.skip, p_served=p.p_served))
        return pats

    def network(self, state):
        rows, keys, dkey, line = [], {}, {}, {}
        pulses, chain_prev = {}, {}

        def add(tid, p, a, b, start, key, dk, ln):
            run = SPEEDS.pattern_run(p, start)
            keep = [j for j in range(a, b + 1) if not (p.stops[j] in p.skip and a < j < b)]
            rows.extend((tid, p.stops[j], m + 1, float(run[j] - run[a] + start)) for m, j in enumerate(keep))
            keys[tid] = key; dkey[tid] = dk; line[tid] = ln
            return float(run[b] - run[a] + start)

        for n, (hd, he) in state.items():
            if hd is None and he is None:
                continue
            for di, (p, cuts) in enumerate(self.lines[n]):
                dk = delay_key(n[1:], di) if n[0] == "R" else "*"
                if n[0] == "R" or not cuts:
                    t = FIRST
                    while t < LAST:
                        h = he if t >= 19 * 60 else hd
                        if h is None:
                            t += PULSE; continue
                        dep = t + (h / 2 if di else 0)
                        add(f"{p.name}@{dep:.1f}", p, 0, len(p.stops) - 1, dep, f"{n}|{di}|{int(t)}", dk, n[1:])
                        t += h
                    continue
                j1, h1 = cuts[0]
                k = 0
                for pt in np.arange(self.phase[h1], LAST + 1, PULSE):
                    h = he if pt >= 19 * 60 else hd
                    if h is None or (h == 2 * PULSE and k % 2):
                        k += 1; continue
                    k += 1
                    if pt < FIRST:
                        continue
                    # first piece: start -> first hub, arriving ARRIVE_BEFORE before the pulse pt
                    arr = pt - ARRIVE_BEFORE
                    run0 = lambda x, p=p, j1=j1: SPEEDS.pattern_run(p, x)[j1] - x  # noqa: E731
                    start = arr - run0(arr - 15); start = arr - run0(start)
                    prev = f"{p.name}#0@{pt:.1f}"
                    add(prev, p, 0, j1, start, f"{n}|{di}|0|{k}", dk, n[1:])
                    pulses.setdefault((h1, pt), ([], []))[0].append(prev)
                    cur_hub, cur_pt, cur_j = h1, pt, j1
                    for m, (j2, h2) in enumerate(cuts[1:] + [(len(p.stops) - 1, None)], start=1):
                        dep = cur_pt + DEPART_AFTER
                        tid = f"{p.name}#{m}@{pt:.1f}"
                        end = add(tid, p, cur_j, j2, dep, f"{n}|{di}|{m}|{k}", dk, n[1:])
                        pulses.setdefault((cur_hub, cur_pt), ([], []))[1].append(tid)
                        chain_prev[tid] = prev
                        if h2 is None:
                            break
                        nxt = self.next_pulse(h2, end + ARRIVE_BEFORE)
                        pulses.setdefault((h2, nxt), ([], []))[0].append(tid)
                        prev, cur_hub, cur_pt, cur_j = tid, h2, nxt, j2
        df = pd.DataFrame(rows + self.tt.school, columns=["trip_id", "stop_id", "stop_sequence", "t"])
        line.update(self.tt.school_line)
        net = MultiPulseNet(df, line, self.tt.stops, 1.0, self.tt.foot)
        net.dkey = {**dkey, **self.tt.school_dkey}
        net.pulses = pulses
        net.chain_prev = chain_prev
        return net, keys

    def score(self, state, detail=False):
        key = json.dumps(sorted(state.items()))
        if key in self.memo and not detail:
            return self.memo[key]
        S, prob = self.S, self.S.prob
        pats = self.patterns(state)
        buses, hours = EN.fleet(pats)
        pen = 0.02 * max(0, max(buses.values()) - prob.budget_peak) + 0.002 * max(0, hours - prob.budget_hours)
        nk = self.network(state)
        home, (overall, overall_p) = self.tt.per_home(nk, metric="both")
        obj = overall / S.today
        worst = max(home[o][0] / S.today_home[o][0] for o in home)
        pen += X.AREA_PEN * max(0, worst - (1 + P.MAX_AREA_LOSS))
        fs = S.freq_share(nk[0]) if S.freq_rule else {}
        short = sum(max(0.0, S.freq_today[a] - X.FREQ_TOL - fs.get(a, 0.0)) for a in S.freq_today) if S.freq_rule else 0.0
        pen += X.FREQ_PEN * short + 0.1 * prob.protected_lost(pats)
        total = obj + pen
        self.memo[key] = total
        if detail:
            return dict(total=total, obj=obj, minutes=overall, perceived=overall_p, pen=pen, buses=max(buses.values()),
                        hours=hours, worst_area=worst, freq_short=short, protected_lost=prob.protected_lost(pats),
                        lines=sum(1 for v in state.values() if v != (None, None)))
        return total

    def neighbour(self, state):
        levels = [None, PULSE, 2 * PULSE]
        s = dict(state)
        n = random.choice(self.names)
        hd, he = s[n]
        r = random.random()
        if r < 0.4:
            hd = random.choice([x for x in levels if x != hd])
        elif r < 0.7:
            he = random.choice([x for x in levels if x != he])
        else:
            on = [m for m in self.names if s[m] != (None, None)]
            off = [m for m in self.names if s[m] == (None, None)]
            if on and off:
                a, b = random.choice(on), random.choice(off)
                s[b], s[a] = s[a], (None, None)
                return s
        s[n] = (hd, he)
        return s


def main():
    hub_set, iters, seed = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
    random.seed(seed)
    M = Multi(hub_set)
    start = sys.argv[4] if len(sys.argv) > 4 else None
    if start:       # a network state of scripts/optimize_tt.py: its lines, at the nearest pulse levels
        raw = json.load(open(start))
        lv = lambda h: None if h is None else (PULSE if h <= 1.5 * PULSE else 2 * PULSE)  # noqa: E731
        cur = {n: (None, None) for n in M.names}
        for k, v in raw.items():
            for n in (f"M{k}", f"R{k}"):
                if n in cur and any(x is not None for x in v.values()):
                    cur[n] = (lv(v.get("09-12")), lv(v.get("19-24")))
    else:           # today's lines, every other pulse
        cur = {n: ((2 * PULSE, 2 * PULSE) if n in M.base_lines else (None, None)) for n in M.names}
    tag = f"data/pulsem_{hub_set}_p{PULSE}_s{seed}"
    it0, log = 0, []
    if os.path.exists(tag + "_ckpt.json"):
        c = json.load(open(tag + "_ckpt.json"))
        cur, best, it0, log = ({k: tuple(v) for k, v in c["cur"].items()}, {k: tuple(v) for k, v in c["best"].items()},
                               c["it"], c["log"])
        random.seed(seed * 1000 + it0)
    else:
        best = dict(cur)
    cur_s, best_s = M.score(cur), M.score(best)
    print("start", it0, M.score(cur, detail=True), flush=True)
    t0 = time.time()
    for it in range(it0, iters):
        T_ = T0 * (1 - it / iters) + 1e-5
        cand = M.neighbour(cur); s = M.score(cand)
        if s < cur_s or random.random() < math.exp(-(s - cur_s) / T_):
            cur, cur_s = cand, s
            if s < best_s:
                best, best_s = cand, s
        log.append(dict(it=it, cur=cur_s, best=best_s))
        if it % 25 == 0:
            print(f"{it} cur {cur_s:.4f} best {best_s:.4f} ({time.time() - t0:.0f}s)", flush=True)
            json.dump(dict(cur=cur, best=best, it=it + 1, log=log), open(tag + "_ckpt.json", "w"))
            json.dump(best, open(tag + ".json", "w"))
    json.dump(best, open(tag + ".json", "w"))
    print("best", M.score(best, detail=True), flush=True)


if __name__ == "__main__":
    main()
