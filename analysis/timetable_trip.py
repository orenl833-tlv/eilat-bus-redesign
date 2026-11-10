"""Timetable journey planner (connection scan) on the real GTFS, as a trip-planner app does it: every actual
departure, the transfer and the walk. Origin: next to שד.ששת הימים/שד.ארגמן; destination: מלון הנסיכה.

Usage (from eilat-transit/):
  python3 analysis/timetable_trip.py                              today's timetable
  python3 analysis/timetable_trip.py real                         today's, run times x 1.24 as measured (SIRI)
  python3 analysis/timetable_trip.py exports/gtfs_full_warm.zip   an option's timetable (winter)
"""
import os
import sys
import numpy as np
import pandas as pd
sys.path.insert(0, ".")
from eilat.evaluate import walk_min
G = "data/gtfs_eilat/"
S = pd.read_csv(G + "stops.csv").set_index("stop_id")
if len(sys.argv) > 1 and sys.argv[1].endswith(".zip"):   # an option's GTFS: already measured run times
    import zipfile
    z = zipfile.ZipFile(sys.argv[1])
    tr = pd.read_csv(z.open("trips.txt")); tr = tr[tr.service_id == "weekday_winter"]
    st = pd.read_csv(z.open("stop_times.txt")); st = st[st.trip_id.isin(tr.trip_id)].sort_values(["trip_id", "stop_sequence"])
    sec = st.arrival_time.str.split(":", expand=True).astype(int) @ [3600, 60, 1]
    st["dep"] = st["arr"] = sec.values
    ln = dict(zip(tr.trip_id, tr.route_id.astype(str)))
    REAL = False
else:
    st = pd.read_csv(G + "stop_times.csv").sort_values(["trip_id", "stop_sequence"])
    tr = pd.read_csv(G + "trips.csv").merge(pd.read_csv(G + "routes.csv")[["route_id", "route_short_name"]], on="route_id")
    ln = dict(zip(tr.trip_id, tr.route_short_name.astype(str)))
    REAL = len(sys.argv) > 1   # scale run times by the measured factor (SIRI: trips take ~1.24 x the timetable)
rows = []
for t, g in st.groupby("trip_id"):
    s, d, a = g.stop_id.values, g.dep.values / 60, g.arr.values / 60
    if REAL:
        a = a[0] + (a - a[0]) * 1.24; d = d[0] + (d - d[0]) * 1.24
    for i in range(len(s) - 1):
        rows.append((d[i], a[i + 1], s[i], s[i + 1], t))
C = sorted(rows)
lat, lon = S.stop_lat, S.stop_lon
ids = list(S.index)
L = np.array([lat[i] for i in ids]); O = np.array([lon[i] for i in ids])
W = walk_min(L[:, None], O[:, None], L[None, :], O[None, :])
foot = {ids[i]: [(ids[j], W[i, j]) for j in np.where((W[i] <= 300 * 1.3 / 75) & (W[i] > 0))[0]] for i in range(len(ids))}
ORIGIN = os.environ.get("ORIGIN", "שד.ששת הימים/שד.ארגמן")      # the stop the home is next to
DEST = os.environ.get("DEST", "מלון הנסיכה")                     # any stop whose name contains this
FROM, TO = (int(x) for x in os.environ.get("HOURS", "6-10").split("-"))
org = S.index[S.stop_name == ORIGIN][0]
olat, olon = lat[org], lon[org]
dest = [i for i in ids if DEST in S.stop_name[i]]
def plan(t0):
    best = {i: np.inf for i in ids}; jp = {}
    for i in ids:
        w = float(walk_min(olat, olon, lat[i], lon[i]))
        if w <= 800 * 1.3 / 75:
            best[i] = t0 + w; jp[i] = ("walk", w)
    trip_in = {}
    for dep, arr, a, b, t in C:
        if dep < t0:
            continue
        if t in trip_in or best[a] <= dep:
            if t not in trip_in:
                trip_in[t] = a
            if arr < best[b]:
                best[b] = arr; jp[b] = (t, trip_in[t])
                for c, w in foot[b]:
                    if arr + w < best[c]:
                        best[c] = arr + w; jp[c] = ("foot", b)
    d = min(dest, key=lambda x: best[x])
    # trace
    legs, x = [], d
    while x in jp and jp[x][0] != "walk":
        k = jp[x]
        if k[0] == "foot":
            x = k[1]; continue
        legs.append(ln[k[0]]); x = k[1]
    return best[d] + 1, list(reversed(legs))
def f(m):
    return f"{int(m // 60):02d}:{int(m % 60):02d}"


for h in np.arange(FROM * 60, TO * 60 + 1, 15):
    arr, legs = plan(h)
    if not np.isfinite(arr):
        print(f(h), "-> no bus reaches it"); continue
    print(f(h), "->", f(arr), f"{arr-h:.0f} min", "+".join(legs) if legs else "walk")
