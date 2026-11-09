"""School dismissal spikes: can the buses near each secondary school take the students let out at one bell?

Bell times and shares (assumption from the Education Ministry's weekly hours: 36 h in grades 7-9; 30-34 h plus
matriculation prep in 10-12; 08:00 start, 45-minute periods, two breaks):
  end after period 6 ~13:15, 7 ~14:10, 8 ~15:00, 9 ~15:45
  grades 7-9:   35% / 45% / 20% / 0%      grades 10-12: 15% / 35% / 35% / 15%
Comprehensive schools (7-12) are taken as half each. Bus share of students: 4% (the calibrated model: school
lines 80-82 carry ~110 a direction a day) and 10% (high case). Supply: places on buses calling at a stop within
300 m of the school in the 15 minutes after the bell = sum over lines (15 / headway) x 85, plus school-line trips
leaving in that window (GTFS times). Output: data/school_peaks.csv
"""
import json
import math

import numpy as np
import pandas as pd

import optimize as O
from eilat import params as P
from eilat.evaluate import walk_min

BELLS = {"13:15": (0.35, 0.15), "14:10": (0.45, 0.35), "15:00": (0.20, 0.35), "15:45": (0.0, 0.15)}
SCHOOLS = {"Rabin": (29.5534, 34.9358, 1191), "Begin": (29.5622, 34.9379, 1084), "Goldwater": (29.5536, 34.9481, 1067)}
SHARES = (0.04, 0.10)
CAP = 85
SCHOOL_LINES = {"80", "80א", "81", "82"}


def period_of(hhmm):
    h = int(hhmm[:2])
    return next(k for k, (a, b) in P.PERIODS.items() if a <= h < b)


def main():
    rows = []
    st = pd.read_csv("data/gtfs_eilat/stop_times.csv"); tr = pd.read_csv("data/gtfs_eilat/trips.csv").merge(
        pd.read_csv("data/gtfs_eilat/routes.csv")[["route_id", "route_short_name"]], on="route_id")
    for tag in ["today", "keep", "full_warm", "full_peak-3_warm"]:
        prob = O.Problem("keep" if tag == "keep" else "full", -3 if "peak-3" in tag else 0)
        if tag == "today":
            net = prob.base
        else:
            sr = json.load(open(f"data/opt_{tag}_seasonal.json"))["winter"]
            net = prob.network({k: {q: (h if h is not None else math.inf) for q, h in v.items()} for k, v in sr.items()})
        stops = prob.sg.stops.set_index("stop_id")
        for name, (lat, lon, n) in SCHOOLS.items():
            near = set(stops.index[walk_min(stops.stop_lat.values, stops.stop_lon.values, lat, lon)
                                   * (P.WALK_KMH * 1000 / 60) / P.DETOUR <= 300])
            for bell, (lo, hi) in BELLS.items():
                students = n * (0.5 * lo + 0.5 * hi)
                q = period_of(bell)
                seats = 0.0; lines = []
                for p in net:
                    if p.line in SCHOOL_LINES:
                        continue
                    h = p.headway.get(q, math.inf)
                    if math.isfinite(h) and any(s in near and s not in p.skip for s in p.stops[:-1]):
                        seats += 15 / h * CAP; lines.append(p.name)
                # school lines: trips leaving within 30 min after the bell that call near the school
                t0 = int(bell[:2]) * 3600 + int(bell[3:]) * 60
                sl = tr[tr.route_short_name.astype(str).isin(SCHOOL_LINES)]
                x = st[st.trip_id.isin(sl.trip_id) & st.stop_id.isin(near) & st.dep.between(t0, t0 + 1800)]
                seats += x.trip_id.nunique() * CAP
                for share in SHARES:
                    riders = students * share
                    rows.append(dict(option=tag, school=name, bell=bell, students_out=round(students), share=share,
                                     riders=round(riders), seats_15min=round(seats), lines=len(lines),
                                     load_ratio=round(riders / seats, 2) if seats else np.inf,
                                     breakeven_share=round(seats / students, 2) if students else np.inf))
        print(tag, "done", flush=True)
    t = pd.DataFrame(rows); t.to_csv("data/school_peaks.csv", index=False)
    pd.set_option("display.width", 200)
    print(t[t.share == 0.10].pivot_table(index=["school", "bell"], columns="option", values="load_ratio").to_string())
    print("\nshare of dismissed students that would fill every passing bus (break-even), lowest per option:")
    print(t.groupby("option").breakeven_share.min().to_string())


if __name__ == "__main__":
    main()
