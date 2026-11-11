"""Screen the lines designed from scratch (eilat/candidates.py designed_lines): add each one alone, every 20
minutes (30 in the evening), to the best timetable-searched network, and plan it on the timetable as buses
really run (scripts/optimize_tt.py). Keeps the lines that save the most door-to-door minutes per bus-hour
added, and the most in total.

Usage: PYTHONPATH=.:scripts:analysis python3 scripts/screen_lines.py [base state]
Output: data/designed_screen.csv, data/designed_keep.json (the lines scripts/optimize_tt.py MODE=design uses)
"""
import json
import math
import os
import sys

import pandas as pd

import optimize_tt as X
from eilat import params as P

BASE = sys.argv[1] if len(sys.argv) > 1 else "data/opt_tt_today_s1.json"
KEEP_RATE, KEEP_TOTAL = 30, 15
CK = "data/designed_screen.csv"


def main():
    if os.path.exists("data/designed_keep.json"):
        os.remove("data/designed_keep.json")            # screen the whole set
    S = X.Search(mode="design")
    st = dict(S.prob.state0)
    for k, v in json.load(open(BASE)).items():
        if k in st:
            st[k] = {q: (h if h is not None else math.inf) for q, h in v.items()}
    b = S.score(st, detail=True)
    print("base", round(b["minutes"], 2), round(b["hours"], 1), flush=True)
    done = pd.read_csv(CK) if os.path.exists(CK) else pd.DataFrame(columns=["line"])
    rows = done.to_dict("records")
    for ln in [k for k in S.prob.lines if k.startswith("D") and k not in set(done.line)]:
        s2 = dict(st); s2[ln] = {q: (30.0 if q == "19-24" else 20.0) for q in P.PERIODS}
        d = S.score(s2, detail=True)
        rows.append(dict(line=ln, minutes=d["minutes"], saved=b["minutes"] - d["minutes"], extra_hours=d["hours"] - b["hours"],
                         run=S.prob.lines[ln][0].run_min("09-12")))
        rows[-1]["saved_per_100h"] = 100 * rows[-1]["saved"] / max(rows[-1]["extra_hours"], 1.0)
        print(ln, {k: round(v, 3) for k, v in rows[-1].items() if k != "line"}, flush=True)
        pd.DataFrame(rows).to_csv(CK, index=False)
    D = pd.DataFrame(rows)
    keep = set(D.nlargest(KEEP_RATE, "saved_per_100h").line) | set(D.nlargest(KEEP_TOTAL, "saved").line)
    keep = sorted(x for x in keep if D.set_index("line").saved[x] > 0)
    json.dump(keep, open("data/designed_keep.json", "w"))
    print(len(keep), "kept;", D.sort_values("saved", ascending=False).head(10).round(3).to_string())


if __name__ == "__main__":
    main()
