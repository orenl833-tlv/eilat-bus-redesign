"""Rough driver-duty check: can each option's bus days be cut into workable driver shifts?

Not a rostering optimisation; a feasibility check with simple, stated rules (assumptions, not the legal text):
- A bus day (block, from scripts/blocking.py) is cut into driver duties only between trips, at a terminal.
- A duty lasts at most DUTY_MAX_H from its first departure to its last arrival, plus SIGN_ON_MIN.
- Where a bus waits >= GAP_SPLIT_MIN (it goes back to the depot), the duty always ends there.
- Driving with no layover of >= BREAK_MIN for more than DRIVE_MAX_H in a row needs a break: a reliever takes
  the bus for one trip (counted as a "break relief").
- Pieces shorter than SHORT_H can't be a shift on their own: they must be paired with another piece into a
  split shift (counted as "short pieces").

Usage: PYTHONPATH=.:scripts python3 scripts/shifts.py   Output: data/shifts.csv
"""
import pandas as pd

import blocking as BL
from eilat import params as P

DUTY_MAX_H = 8.5
SIGN_ON_MIN = 15
GAP_SPLIT_MIN = 60
BREAK_MIN = 30
DRIVE_MAX_H = 4.5
SHORT_H = 3.0


def duties(block):
    """Cut one bus day into duties; returns a list of (start, end, break_reliefs)."""
    t = block.sort_values("start")
    out, cur = [], []
    for r in t.itertuples():
        if cur and (r.start - cur[-1].end >= GAP_SPLIT_MIN or r.end - cur[0].start > DUTY_MAX_H * 60 - SIGN_ON_MIN):
            out.append(cur); cur = []
        cur.append(r)
    if cur:
        out.append(cur)
    res = []
    for d in out:
        reliefs, run_start = 0, d[0].start
        for a, b in zip(d[:-1], d[1:], strict=True):
            if b.start - a.end >= BREAK_MIN:
                run_start = b.start
            elif b.end - run_start > DRIVE_MAX_H * 60:
                reliefs += 1; run_start = b.end      # a reliever drives trip b; the driver's break
        res.append((d[0].start, d[-1].end, reliefs))
    return res


def main():
    st = pd.read_csv("data/stops_all.csv").set_index("stop_id")
    rows = []
    for tag in ["today", "keep", "full_warm", "full_peak-3_warm"]:
        for se in (["winter"] if tag == "today" else P.SEASONS):
            trips = BL.option_trips(tag, se, st)
            _, _, blocks = BL.block(trips, st)
            D = pd.DataFrame([d for b in blocks for d in duties(b)], columns=["start", "end", "reliefs"])
            D["h"] = (D.end - D.start + SIGN_ON_MIN) / 60
            full = D[D.h >= SHORT_H]
            rows.append(dict(option=tag, season=se, buses=len(blocks), pieces=len(D), full_duties=len(full),
                             short_pieces=int((D.h < SHORT_H).sum()),
                             # two short pieces make one split shift
                             drivers_needed=len(full) + int(-(-(D.h < SHORT_H).sum() // 2)),
                             paid_driver_hours=round(D.h.sum(), 1), mean_duty_h=round(full.h.mean(), 2),
                             break_reliefs=int(D.reliefs.sum()),
                             first_out=f"{int(D.start.min() // 60):02d}:{int(D.start.min() % 60):02d}",
                             last_in=f"{int(D.end.max() // 60):02d}:{int(D.end.max() % 60):02d}"))
            print(rows[-1], flush=True)
    pd.DataFrame(rows).to_csv("data/shifts.csv", index=False)


if __name__ == "__main__":
    main()
