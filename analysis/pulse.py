"""A pulse network: every line is a spoke from one hub, and all spokes meet there at the same moments.

- Spokes: the fastest path along streets buses drive today (eilat/candidates.py StopGraph), hub -> end and
  end -> hub, for every end (neighbourhood anchors and main places), and through two ends in a row when that
  adds little; near-duplicates dropped.
- Pulses every PULSE minutes, 06:00-23:00. A spoke runs every pulse (20) or every other pulse (40), by day
  (06-19) and evening (19-23), or not at all. Inbound buses are timed to reach the hub ARRIVE_BEFORE minutes before
  the pulse; outbound buses leave DEPART_AFTER minutes after it.
- Holding: an outbound bus leaves when the latest inbound bus of its pulse is in plus the transfer time, but at
  most HOLD_MAX minutes late. It starts at the hub, so it has no delay of its own to carry; only its run-time
  deviation is drawn. Inbound buses are delayed as real trips are (data/ride_delays.csv).
- Each candidate is scored as in scripts/optimize_tt.py (demand-weighted trips, GPS run times per segment, hour and
  direction, real delays, 2 min a transfer), with the same budget and rules (area loss, the 20-min frequency rule).

Usage: MODE=design OD=demand FREQ_RULE=1 PYTHONPATH=.:scripts:analysis python3 analysis/pulse.py HUB ITERS SEED
  HUB: central_station | city_hall.   Output: data/pulse_<hub>_s<seed>.json (+ _ckpt.json)
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
from eilat import candidates as C
from eilat import network as EN
from eilat import params as P
from eilat.evaluate import walk_min
from eilat.speeds import Speeds
from eilat.timetable import Network, delay_key

HUBS = {"central_station": [49835], "city_hall": [12356, 12625]}
PULSE, ARRIVE_BEFORE, DEPART_AFTER, HOLD_MAX = 20, 2.0, 3.0, 5.0
FIRST, LAST = 6 * 60, 23 * 60
LEVELS = [None, 20, 40]
T0 = 0.004
SPEEDS = Speeds()


def spokes(sg, hub_stops, ends):
    """Two-way spokes {name: (outbound stops, inbound stops)}: hub -> end (-> second end) and back."""
    out, sets = {}, []
    h = hub_stops[0]

    def run(st):
        return sum(sg.edge_min.get((u, v), 1.0) for u, v in zip(st[:-1], st[1:], strict=True))
    cand = []
    for e in ends:
        if e in hub_stops or e not in sg.ix:
            continue
        o, i = sg.path(h, e), sg.path(e, h)
        if o and i and len(o) >= 4:
            cand.append((f"S{e}", o, i))
    for e1 in ends:
        for e2 in ends:
            if e1 == e2 or e1 in hub_stops or e2 in hub_stops:
                continue
            o, i = sg.through([h, e1, e2]), sg.through([e2, e1, h])
            d = sg.path(h, e2)
            if o and i and d and run(o) <= 1.3 * run(d) and len(o) >= 6:
                cand.append((f"S{e1}_{e2}", o, i))
    cand.sort(key=lambda c: run(c[1]) + run(c[2]))
    for name, o, i in cand:
        s = set(o) | set(i)
        if any(len(s & x) / len(s | x) > 0.85 for x in sets):
            continue
        out[name] = (o, i); sets.append(s)
    return out


def line_spokes(prob, hub_stops, max_m=300.0):
    """Spokes cut from the pool's lines (today's lines, their variants, new lines) at the hub, so a pulse network
    keeps their coverage of the neighbourhoods: a pattern passing within max_m of the hub is cut at its nearest
    stop. A one-way loop -> one spoke (out: hub -> on round the loop, in: the loop back to the hub); a two-way
    line -> a spoke each side (out from one direction, in from the other). {name: (out Pattern, in Pattern)}"""
    st = prob.sg.stops.set_index("stop_id")
    hl = [(float(st.stop_lat[h]), float(st.stop_lon[h])) for h in hub_stops]

    def cut(p):
        d = [min(walk_min(st.stop_lat[s_], st.stop_lon[s_], a, b) for a, b in hl) * P.WALK_KMH * 1000 / 60 for s_ in p.stops]
        j = int(np.argmin(d))
        return j if d[j] <= max_m else None

    def piece(p, a, b, name):
        seg = {q: list(v[a:b - 1]) for q, v in p.seg_min.items()}
        stops = p.stops[a:b]
        return EN.Pattern(name=name, line=name.split("/")[0], stops=list(stops), seg_min=seg, headway={},
                          skip={x for x in p.skip if x in stops[1:-1]}, p_served=dict(p.p_served))
    out = {}
    for ln, pats in prob.lines.items():
        cuts = [cut(p) for p in pats]
        if any(c is None for c in cuts):
            out[f"R{ln}"] = tuple(pats)          # does not pass the hub: runs as an ordinary line
            continue
        if len(pats) == 1:
            p, j = pats[0], cuts[0]
            if j < 2 or j > len(p.stops) - 3:
                out[f"R{ln}"] = tuple(pats); continue
            out[f"L{ln}"] = (piece(p, j, len(p.stops), f"L{ln}/0"), piece(p, 0, j + 1, f"L{ln}/1"))
        elif len(pats) == 2:
            (p0, j0), (p1, j1) = (pats[0], cuts[0]), (pats[1], cuts[1])
            if min(j0, j1) < 2 or j0 > len(p0.stops) - 3 or j1 > len(p1.stops) - 3:
                out[f"R{ln}"] = tuple(pats); continue
            # side A: where direction 0 starts (= where direction 1 ends); side B: the other end
            out[f"L{ln}A"] = (piece(p1, j1, len(p1.stops), f"L{ln}A/0"), piece(p0, 0, j0 + 1, f"L{ln}A/1"))
            out[f"L{ln}B"] = (piece(p0, j0, len(p0.stops), f"L{ln}B/0"), piece(p1, 0, j1 + 1, f"L{ln}B/1"))
    return out


class PulseNet(Network):
    """A Network whose realize() also applies the hub holding rule."""

    def realize(self, sampler, seed, keys=None, dkey=None):
        real = super().realize(sampler, seed, keys, dkey)
        for inbound, outbound in self.pulses:
            arr = [real.realized_times(t)[1][-1] for t in inbound if t in real.trips]
            latest = max(arr) if arr else -1e9
            for t in outbound:
                if t not in real.trips:
                    continue
                sched = self.trips[t][1][0]
                hold = min(max(0.0, latest + X.T.TRANSFER_MIN - sched), HOLD_MAX)
                real.delays[t] = (hold, real.delays[t][1])
        real._build(real.delays)
        return real


class Pulse:
    def __init__(self, hub):
        self.S = X.Search()                      # today's reference, trips, sampler, frequency rule
        self.tt = self.S.tt
        prob = self.S.prob
        self.sg = prob.sg
        self.hub = HUBS[hub]
        ends = sorted(set(prob.anchors.values()) | set(C.ANCHORS))
        self.spokes = spokes(self.sg, self.hub, ends)
        self.pats = {n: (C.make(self.sg, f"{n}/0", n, o), C.make(self.sg, f"{n}/1", n, i)) for n, (o, i) in self.spokes.items()}
        self.pats.update(line_spokes(prob, self.hub))
        self.names = sorted(self.pats)
        base = {p.line for p in prob.base if p.line not in X.O.SCHOOL}
        self.base_spokes = [n for n in self.names if (n.startswith("L") and n[1:].rstrip("AB") in base) or (n.startswith("R") and n[1:] in base)]
        self.memo = {}
        print(f"hub {hub}: {len(self.names)} spokes", flush=True)

    def patterns(self, state):
        """Network patterns with headways (for the budget and the rules of scripts/optimize.py)."""
        pats = list(self.S.prob.fixed)
        for n, (hd, he) in state.items():
            if hd is None and he is None:
                continue
            hw = {q: (he if q == "19-24" else hd) or math.inf for q in P.PERIODS}
            for p in self.pats[n]:
                q = EN.Pattern(name=p.name, line=p.line, stops=p.stops, seg_min=p.seg_min, headway=dict(hw))
                pats.append(q)
        return pats

    def network(self, state):
        rows, keys, dkey, line = [], {}, {}, {}
        pulses = []
        k = 0
        for t in range(FIRST, LAST + 1, PULSE):
            inbound, outbound = [], []
            for n, (hd, he) in state.items():
                h = he if t >= 19 * 60 else hd
                if n.startswith("R") or h is None or (h == 40 and k % 2):
                    continue
                po, pi = self.pats[n]
                # inbound: reach the hub ARRIVE_BEFORE before the pulse (run time at that hour, two passes)
                arr = t - ARRIVE_BEFORE
                run = lambda x, p=pi: SPEEDS.pattern_run(p, x)[-1] - x  # noqa: E731
                start = arr - run(arr - 20)
                start = arr - run(start)
                if start >= FIRST - 30:
                    tid = f"{n}/1@{start:.1f}"
                    cum = SPEEDS.pattern_run(pi, start)
                    rows += [(tid, s, j + 1, float(cum[j])) for j, s in enumerate(pi.stops)]
                    keys[tid] = f"{n}|in|{k}"; dkey[tid] = "*"; line[tid] = n; inbound.append(tid)
                if t + DEPART_AFTER < LAST + 1:
                    dep = t + DEPART_AFTER
                    tid = f"{n}/0@{dep:.1f}"
                    cum = SPEEDS.pattern_run(po, dep)
                    rows += [(tid, s, j + 1, float(cum[j])) for j, s in enumerate(po.stops)]
                    keys[tid] = f"{n}|out|{k}"; dkey[tid] = "*"; line[tid] = n; outbound.append(tid)
            pulses.append((inbound, outbound))
            k += 1
        for n, (hd, he) in state.items():                 # ordinary lines: every h, the second direction half a headway later
            if not n.startswith("R") or (hd is None and he is None):
                continue
            for di, p in enumerate(self.pats[n]):
                t = FIRST
                while t < LAST:
                    h = he if t >= 19 * 60 else hd
                    if h is None:
                        t += PULSE; continue
                    dep = t + (h / 2 if di else 0)
                    tid = f"{p.name}@{dep:.1f}"
                    cum = SPEEDS.pattern_run(p, dep)
                    keep = [j for j, s_ in enumerate(p.stops) if not (s_ in p.skip and 0 < j < len(p.stops) - 1)]
                    rows += [(tid, p.stops[j], m + 1, float(cum[j])) for m, j in enumerate(keep)]
                    keys[tid] = f"{n}|{di}|{int(t)}"; dkey[tid] = delay_key(n[1:], di); line[tid] = n[1:]
                    t += h
        df = pd.DataFrame(rows + self.tt.school, columns=["trip_id", "stop_id", "stop_sequence", "t"])
        line.update(self.tt.school_line)
        net = PulseNet(df, line, self.tt.stops, 1.0, self.tt.foot)
        net.dkey = {**dkey, **self.tt.school_dkey}
        net.pulses = pulses
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
                        spokes=sum(1 for v in state.values() if v != (None, None)))
        return total

    def neighbour(self, state):
        s = dict(state)
        n = random.choice(self.names)
        hd, he = s[n]
        r = random.random()
        if r < 0.4:
            hd = random.choice([x for x in LEVELS if x != hd])
        elif r < 0.7:
            he = random.choice([x for x in LEVELS if x != he])
        else:   # swap a running spoke for one that is off
            on = [m for m in self.names if s[m] != (None, None)]
            off = [m for m in self.names if s[m] == (None, None)]
            if on and off:
                a, b = random.choice(on), random.choice(off)
                s[b], s[a] = s[a], (None, None)
                return s
        s[n] = (hd, he)
        return s


def main():
    hub, iters, seed = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
    random.seed(seed)
    Pz = Pulse(hub)
    # start: every single-end spoke every 40 min by day and evening (cheap, covers everything)
    # start: today's lines as a pulse network (each cut at the hub), every 20 min by day and 40 in the evening
    cur = {n: ((20, 40) if n in Pz.base_spokes else (None, None)) for n in Pz.names}
    tag = f"data/pulse_{hub}_s{seed}"
    it0, log = 0, []
    if os.path.exists(tag + "_ckpt.json"):
        c = json.load(open(tag + "_ckpt.json"))
        cur, best, it0, log = ({k: tuple(v) for k, v in c["cur"].items()}, {k: tuple(v) for k, v in c["best"].items()},
                               c["it"], c["log"])
        random.seed(seed * 1000 + it0)
    else:
        best = dict(cur)
    cur_s, best_s = Pz.score(cur), Pz.score(best)
    print("start", it0, Pz.score(cur, detail=True), flush=True)
    t0 = time.time()
    for it in range(it0, iters):
        T_ = T0 * (1 - it / iters) + 1e-5
        cand = Pz.neighbour(cur); s = Pz.score(cand)
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
    print("best", Pz.score(best, detail=True), flush=True)


if __name__ == "__main__":
    main()
