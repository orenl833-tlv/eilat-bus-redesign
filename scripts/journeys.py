"""Example journeys: what a real trip looks like today and in each option (evening ending at 23:00).

For every home point x key place x period (winter weekday) the model's best route is traced (the same
shortest-path search the evaluation uses): walk to the stop, wait, ride, transfer, walk to the door. A rider
takes the route with the lowest perceived time, or walks if that is better.

Actual minutes (not perceived) are reported:
- wait = half the combined headway of the lines that serve the leg, as the model assumes;
- people who time their walk to a rare bus wait less.

Chosen examples, ranked by actual door-to-door minutes, option 2 vs today:
- the biggest gains;
- the biggest losses;
- a few everyday trips.
Each comes with its itinerary in today's network and all three options.

Usage: PYTHONPATH=.:scripts python3 scripts/journeys.py   Output: data/journeys.json
"""
import json
import math

import numpy as np

import blocking as BL
import evening as EV
import optimize as O
from eilat import demand as Dm
from eilat import params as P
from export_page import public_name

SEASON = "winter"
NETS = {"today": "היום", "keep": "אפשרות 1", "full_warm": "אפשרות 2", "full_peak-3_warm": "אפשרות 3"}
PLACE_HE = {
    "City hall / centre": "העירייה ומרכז העיר", "Old central station (Star Eilat)": "התחנה המרכזית הישנה (Star Eilat)",
    "Hotels, North Beach": "המלונות בחוף הצפוני", "Ice Mall": "קניון אייס מול", "Mall HaYam": "קניון מול הים",
    "Big centre": "מרכז ביג", "Industrial zone / depot": "אזור התעשייה", "Yoseftal hospital": "בית החולים יוספטל",
    "Eilat campus": "קמפוס אילת", "Rabin high school": "תיכון רבין", "Begin high school": "תיכון בגין",
    "Goldwater high school": "תיכון גולדווטר", "Coral Beach": "חוף האלמוגים", "Taba / Princess": "מלון הנסיכה ומעבר טאבה",
    "Port": "נמל אילת", "City entrance terminal": "חנה וסע בכניסה לעיר",
}
# when a trip to each place makes sense (school places only in the morning, etc.)
WHEN = {"Rabin high school": ["06-09"], "Begin high school": ["06-09"], "Goldwater high school": ["06-09"],
        "Eilat campus": ["06-09", "09-12"], "Industrial zone / depot": ["06-09", "15-19"],
        "Yoseftal hospital": ["06-09", "09-12", "12-15"], "Port": ["06-09"], "Hotels, North Beach": None,
        "Coral Beach": ["09-12", "12-15", "15-19", "19-24"]}
PERIOD_HE = {"06-09": "בבוקר (7:30)", "09-12": "באמצע הבוקר (10:30)", "12-15": "בצהריים (13:30)",
             "15-19": "אחר הצהריים (17:00)", "19-24": "בערב (21:00)"}


def trace(res, i, j, L, pats, stop_name):
    """The best route from source row i to point j: list of steps."""
    ns, npt, pred, lt = res["ns"], res["npt"], res["pred"], res["leg_type"]
    node, path = 2 * ns + npt + j, []
    while True:
        p = pred[i, node]
        if p < 0:
            break
        path.append((int(p), int(node), lt.get((int(p), int(node)))))
        node = int(p)
    path.reverse()
    return path


def itinerary(m, res, i, j, pats, names, w_walk):
    ev = m.ev
    ns = res["ns"]
    pt_i = int(res["src"][i])
    gc, walk = float(res["gc_bus"][i, j]), float(res["walk"][i, j])
    walk_min = float(ev.direct[pt_i, j])
    if not math.isfinite(gc) or walk <= gc:
        return dict(mode="walk", total=round(walk_min), walk=round(walk_min), perceived=round(walk))
    L = res["legs"]
    steps, tot = [], dict(walk=0.0, wait=0.0, ride=0.0, transfers=-1)
    for u, v, t in trace(res, i, j, L, pats, names):
        if t == 2:     # walk from the door to a stop
            s = v; d = float(ev.acc[pt_i, s]); tot["walk"] += d
            steps.append(dict(kind="walk", min=round(d, 1), to=names[s]))
        elif t == 1:   # ride u -> v-ns
            a, b = u, v - ns
            g = L[(L.u == a) & (L.v == b)]
            F = g.f.sum(); wait = 0.5 / F; ivt = float((g.ivt * g.f).sum() / F)
            lines = []
            for r in g.itertuples():
                pat = pats[int(r.k)]
                stops = sum(1 for x in range(int(r.ia) + 1, int(r.ib) + 1) if pat.stops[x] not in pat.skip)
                disp, note = public_name(pat.line)
                lines.append(dict(line=disp, note=note, every=round(1 / r.f), stops=stops, ride=round(float(r.ivt), 1)))
            seen = {}
            for x in lines:
                seen.setdefault(x["line"], x)
            tot["wait"] += wait; tot["ride"] += ivt; tot["transfers"] += 1
            steps.append(dict(kind="ride", lines=list(seen.values()), wait=round(wait, 1), ride=round(ivt, 1),
                              board=names[a], alight=names[b]))
        elif t == 0 and u - ns != v:   # walk between stops at a transfer
            d = float(ev.tr[u - ns, v]); tot["walk"] += d
            steps.append(dict(kind="walk", min=round(d, 1), to=names[v]))
        elif t == 3:   # walk from the last stop to the door
            s = u - ns; d = float(ev.acc[j, s]); tot["walk"] += d
            steps.append(dict(kind="walk", min=round(d, 1), to="היעד"))
    total = tot["walk"] + tot["wait"] + tot["ride"]
    return dict(mode="bus", total=round(total), walk=round(tot["walk"]), wait=round(tot["wait"]), ride=round(tot["ride"]),
                transfers=max(tot["transfers"], 0), perceived=round(gc), steps=steps)


def main():
    probs = {"full": O.Problem("full"), "keep": O.Problem("keep")}
    m = probs["full"].m
    names = {i: n for i, n in enumerate(m.ev.stops.stop_name)}
    att_names = list(Dm.ATTRACTORS.name)
    nets = {"today": probs["full"].base}
    for tag in ["keep", "full_warm", "full_peak-3_warm"]:
        nets[tag] = EV.thinned(BL.option_net(tag, SEASON), 23)
    homes = m.homes
    res = {(t, q): m.ev.run(nets[t], q, w_walk=P.W_WALK, sources=homes) for t in NETS for q in P.PERIODS}
    # door-to-door minutes for every home x place x period, today vs option 2
    cand = []
    for q in P.PERIODS:
        for a_i, name in enumerate(att_names):
            if WHEN.get(name) and q not in WHEN[name]:
                continue
            j = int(m.att[a_i])
            for i, h in enumerate(homes):
                if m.ev.direct[h, j] < 15:      # a short walk: not a bus trip
                    continue
                it = {t: itinerary(m, res[(t, q)], i, j, nets[t], names, P.W_WALK) for t in NETS}
                cand.append(dict(home=int(h), area=int(m.pts.area.values[h]), place=name, period=q, it=it,
                                 delta=it["full_warm"]["total"] - it["today"]["total"]))
    cand.sort(key=lambda c: c["delta"])

    def pick(pool, n, used):
        out = []
        for c in pool:
            key = (c["area"], c["place"])
            if key in used or any(c["place"] == o["place"] for o in out):
                continue
            used.add(key); out.append(c)
            if len(out) == n:
                break
        return out
    used = set()
    best = pick(cand, 3, used)
    worst = pick(list(reversed(cand)), 3, used)
    mid = [c for c in cand if c["place"] in ("Yoseftal hospital", "Eilat campus") and c["period"] in ("09-12", "06-09")]
    typical = pick(sorted(mid, key=lambda c: abs(c["delta"] + 3)), 2, used)
    out = []
    for group, cs in (("best", best), ("worst", worst), ("typical", typical)):
        for c in cs:
            h = c["home"]
            near = int(np.argmin(m.ev.acc[h]))
            out.append(dict(group=group, area=c["area"], home_stop=names[near], place=PLACE_HE[c["place"]], period=c["period"],
                            when=PERIOD_HE[c["period"]], nocar=round(float(m.pts.nocar.values[h]) * 100),
                            delta=c["delta"], options={NETS[t]: c["it"][t] for t in NETS}))
            print(group, c["area"], c["place"], c["period"], {t: c["it"][t]["total"] for t in NETS}, flush=True)
    json.dump(out, open("data/journeys.json", "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
