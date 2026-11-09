"""Driver duties: can each option's bus days be staffed, and what do the extra drivers and split shifts cost?

Not a rostering optimisation: a feasibility check with stated rules.
Law: Traffic Regulation 168(a) (gov.il, "שעות נהיגה – תקנה 168"):
- at least 7 h rest before a working day;
- at most 12 h driving in 24 h (68 h in 7 days);
- a break of at least 30 min in every 4 h of continuous driving;
- more than 9 h driving needs a 1 h break after 6 h.
Assumptions (not law): duty <= DUTY_MAX_H paid incl. sign-on; a split shift = two pieces >= SPLIT_GAP_MIN
apart, unpaid gap, spread <= SPREAD_MAX_H; a short piece can also be up to OVERTIME_H of overtime after a
straight shift; a piece left over is paid at least MIN_PAID_H.

1. A bus day (block, scripts/blocking.py) is cut into pieces between trips: always where the bus waits
   >= DEPOT_GAP_MIN (it goes back to the depot), and into the fewest near-equal pieces <= DUTY_MAX_H.
2. Inside a piece, continuous driving with no layover of >= BREAK_MIN for more than DRIVE_MAX_H: a reliever
   drives the next trip (a "break relief", paid as one short piece of RELIEF_H).
3. Pieces >= SHORT_H are straight shifts. Shorter ones are paired into split shifts (early piece + late
   piece, greedy by start time), then given as overtime to a straight shift; the rest are paid MIN_PAID_H.
4. Cost a weekday = paid hours x DRIVER_COST_H + split shifts x SPLIT_PREMIUM; a year = seasons weighted by
   their months over WEEKDAYS_PER_YEAR. Headcount = the busiest season's duties x ROSTER_FACTOR.

Usage: PYTHONPATH=.:scripts python3 scripts/shifts.py   Output: data/shifts.csv
"""
import pandas as pd

import blocking as BL
from eilat import params as P

DUTY_MAX_H = 8.5
SIGN_ON_MIN = 15
DEPOT_GAP_MIN = 60
BREAK_MIN = 30          # Reg. 168(a)(3)
DRIVE_MAX_H = 4.0       # Reg. 168(a)(3)
SHORT_H = 4.0
SPLIT_GAP_MIN = 60
SPREAD_MAX_H = 13.0
MIN_PAID_H = 4.0
RELIEF_H = 1.0
OVERTIME_H = 2.0        # Hours of Work and Rest Law: overtime paid 125% for the first 2 hours
# pay: the national authority's proposed floor 55.18 NIS/h + 6 NIS/h retention grant (Oct 2026), x 1.35 employer
# cost (pension, severance, national insurance, holiday, sick). Tested 70-100.
DRIVER_COST_H = round((55.18 + 6) * 1.35)
SPLIT_PREMIUM = 60      # assumption: per split shift (no published figure found); tested 0-120
ROSTER_FACTOR = 1.25    # assumption: rest days (Reg. 168(a)(5)), holiday, sickness, training
# "standard": duties <= 8.5 h; "overtime": a duty may run to 10.5 h, the last 2 h paid as overtime (the Hours of
# Work and Rest Law allows overtime; Reg. 168 allows 12 h driving)
SCENARIOS = {"standard": DUTY_MAX_H, "overtime": DUTY_MAX_H + OVERTIME_H}


def _balanced(seg, dmax):
    """Cut a run of trips (no depot gap) into the fewest pieces <= DUTY_MAX_H, the cuts at trip ends nearest
    to equal shares, as a scheduler places relief points (a greedy cut from the morning leaves short tails)."""
    span = seg[-1].end - seg[0].start + SIGN_ON_MIN
    k = -(-span // (dmax * 60))
    while True:
        cuts, out, i0 = [], [], 0
        for q in range(1, int(k)):
            target = seg[0].start + q * span / k
            i = min(range(i0 + 1, len(seg)), key=lambda j: abs(seg[j].start - target), default=None)
            if i is None:
                break
            cuts.append(i); i0 = i
        bounds = [0, *cuts, len(seg)]
        out = [seg[a:b] for a, b in zip(bounds[:-1], bounds[1:], strict=True) if b > a]
        if all(x[-1].end - x[0].start <= dmax * 60 - SIGN_ON_MIN for x in out) or k >= len(seg):
            return out
        k += 1


def pieces(block, dmax=DUTY_MAX_H):
    """Cut one bus day into pieces; returns [(start, end, reliefs)]."""
    t = list(block.sort_values("start").itertuples())
    runs, cur = [], []
    for r in t:
        if cur and r.start - cur[-1].end >= DEPOT_GAP_MIN:
            runs.append(cur); cur = []
        cur.append(r)
    if cur:
        runs.append(cur)
    out = [x for run in runs for x in _balanced(run, dmax)]
    res = []
    for d in out:
        reliefs, run_start = 0, d[0].start
        for a, b in zip(d[:-1], d[1:], strict=True):
            if b.start - a.end >= BREAK_MIN:
                run_start = b.start
            elif b.end - run_start > DRIVE_MAX_H * 60:
                reliefs += 1; run_start = b.end      # a reliever drives trip b while the driver takes the break
        res.append((d[0].start, d[-1].end, reliefs))
    return res


duties = pieces   # name kept for the tests


def staff(P_):
    """Straight shifts, split shifts and leftovers from a day's pieces."""
    D = pd.DataFrame(P_, columns=["start", "end", "reliefs"])
    D["h"] = (D.end - D.start + SIGN_ON_MIN) / 60
    full, short = D[D.h >= SHORT_H], D[D.h < SHORT_H].sort_values("start")
    used, splits = set(), []
    for i, a in short.iterrows():
        if i in used:
            continue
        for j, b in short.iterrows():
            if j in used or j == i or b.start < a.end + SPLIT_GAP_MIN or (b.end - a.start) / 60 > SPREAD_MAX_H:
                continue
            used |= {i, j}; splits.append(a.h + b.h); break
    left = short[~short.index.isin(used)]
    # what is left: overtime for a straight-shift driver whose duty ended >= BREAK_MIN before (paid x1.25,
    # at most OVERTIME_H, spread <= SPREAD_MAX_H)
    ot_h, taken, fl = 0.0, set(), full.sort_values("end")
    for i, a in left.iterrows():
        for j, b in fl.iterrows():
            if j in taken or a.start < b.end + BREAK_MIN or a.h > OVERTIME_H or (a.end - b.start) / 60 > SPREAD_MAX_H:
                continue
            taken.add(j); ot_h += a.h; used.add(i); break
    left = short[~short.index.isin(used)]
    reliefs = int(D.reliefs.sum())
    # hours of a long duty beyond DUTY_MAX_H are overtime (x1.25)
    paid = (full.h.sum() + 0.25 * (full.h - DUTY_MAX_H).clip(lower=0).sum() + sum(splits) + ot_h * 1.25
            + left.h.clip(lower=MIN_PAID_H).sum() + reliefs * RELIEF_H)
    return dict(straight=len(full), split=len(splits), overtime=len(taken), unpaired=len(left), reliefs=reliefs,
                # reliefs are covered by spare drivers, each doing ~6 one-hour reliefs a shift
                duties=len(full) + len(splits) + len(left) + -(-reliefs // 6), paid_h=round(paid, 1), work_h=round(D.h.sum() + reliefs * RELIEF_H, 1),
                cost_day=round(paid * DRIVER_COST_H + len(splits) * SPLIT_PREMIUM))


def main():
    st = pd.read_csv("data/stops_all.csv").set_index("stop_id")
    rows = []
    for tag in ["today", "keep", "full_warm", "full_peak-3_warm"]:
        for se in P.SEASONS:
            trips = BL.option_trips(tag, se, st)
            if tag == "today" and se == "summer":
                trips = trips[~trips.line.isin(BL.SCHOOL)]     # no school trips in the holiday
            _, _, blocks = BL.block(trips, st)
            for sc, dmax in SCENARIOS.items():
                r = staff([p for b in blocks for p in pieces(b, dmax)])
                rows.append(dict(scenario=sc, option=tag, season=se, buses=len(blocks), **r))
                print(rows[-1], flush=True)
    R = pd.DataFrame(rows)
    w = {s: v["months"] / 12 * P.WEEKDAYS_PER_YEAR for s, v in P.SEASONS.items()}
    R["weekdays"] = R.season.map(w)
    R.to_csv("data/shifts.csv", index=False)
    out = []
    for sc, g in R.groupby("scenario"):
        g = g.assign(cost_year=g.cost_day * g.weekdays, hours_year=g.paid_h * g.weekdays, splits_year=g.split * g.weekdays)
        Y = g.groupby("option").agg(
            cost_year=("cost_year", "sum"), hours_year=("hours_year", "sum"), splits_year=("splits_year", "sum"),
            duties_max=("duties", "max"), splits_max=("split", "max"))
        Y["headcount"] = (Y.duties_max * ROSTER_FACTOR).round()
        base = Y.loc["today"]
        Y["extra_drivers"] = Y.headcount - base.headcount
        Y["extra_cost_year_mnis"] = ((Y.cost_year - base.cost_year) / 1e6).round(2)
        Y["extra_hours_pct"] = ((Y.hours_year / base.hours_year - 1) * 100).round(1)
        # sensitivity: driver cost 70-100 NIS/h, split premium 0-120 NIS
        dh, ds = Y.hours_year - base.hours_year, Y.splits_year - base.splits_year
        Y["extra_cost_low_mnis"] = ((dh * 70 + ds.clip(upper=0) * 120) / 1e6).round(2)
        Y["extra_cost_high_mnis"] = ((dh * 100 + ds.clip(lower=0) * 120) / 1e6).round(2)
        out.append(Y.assign(scenario=sc))
    Y = pd.concat(out)
    Y.to_csv("data/shifts_year.csv")
    print(Y.T.to_string())


if __name__ == "__main__":
    main()
