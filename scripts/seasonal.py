"""Stage 2 of the search: the line structure is fixed (from optimize.py); headways are tuned separately for each
season, each under today's budget (buses at once, bus-hours). One network, frequencies by season (agreed).

Usage: PYTHONPATH=. python3 scripts/seasonal.py <tag> [iterations per season] [peak_delta]
Output: data/opt_<tag>_seasonal.json  {season: state}
"""
import copy
import json
import math
import random
import sys

import optimize as O
from eilat import params as P


def load_state(path):
    raw = json.load(open(path))
    return {k: {q: (h if h is not None else math.inf) for q, h in v.items()} for k, v in raw.items()}


def main():
    tag = sys.argv[1]; iters = int(sys.argv[2]) if len(sys.argv) > 2 else 400
    peak_delta = int(sys.argv[3]) if len(sys.argv) > 3 else 0
    mode = "keep" if tag.startswith("keep") else ("moderate" if tag.startswith("moderate") else "full")
    random.seed(2)
    prob = O.Problem(mode, peak_delta)
    best_all = load_state(f"data/opt_{tag}.json")
    active = [k for k, v in best_all.items() if any(math.isfinite(h) for h in v.values())]
    out = {}
    for season in P.SEASONS:
        O.SEASONS[:] = [season]          # score this season only
        cur = copy.deepcopy(best_all); cur_s = prob.score(cur); best, best_s = cur, cur_s
        for it in range(iters):
            s = copy.deepcopy(cur)
            ln = random.choice(active); q = random.choice(list(P.PERIODS)); h = s[ln][q]
            i = O.LEVELS.index(h) if math.isfinite(h) else len(O.LEVELS)
            i = max(0, min(len(O.LEVELS), i + random.choice([-1, 1])))
            s[ln][q] = O.LEVELS[i] if i < len(O.LEVELS) else math.inf
            sc = prob.score(s)
            T = 0.002 * (1 - it / iters) + 1e-5
            if sc < cur_s or random.random() < math.exp(-(sc - cur_s) / T):
                cur, cur_s = s, sc
                if sc < best_s:
                    best, best_s = s, sc
        out[season] = {k: {q: (h if math.isfinite(h) else None) for q, h in v.items()} for k, v in best.items()}
        print(season, "score", round(best_s, 4), prob.score(best, detail=True), flush=True)
    O.SEASONS[:] = list(P.SEASONS)
    json.dump(out, open(f"data/opt_{tag}_seasonal.json", "w"), indent=0)


if __name__ == "__main__":
    main()
