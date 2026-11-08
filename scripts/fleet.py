"""How many buses Eilat really runs at once, and for how many hours, from SIRI reports (fetch_siri.py).

A ride's service interval is its first to its last report. Two measures:
- in service: minutes covered by at least one ride of that bus (carrying passengers on a trip);
- in use: in service plus short layovers (gap of at most LAYOVER minutes between two rides of the
  same bus), which is what the fleet constraint really is: a bus waiting 10 minutes at a terminal is
  not available for another line.
Lines are named from the GTFS routes file (line_ref = route_id). Urban lines are those inside the city;
airport / regional lines (30, 31, 32, 50) are counted separately; intercity lines passing through the
box are left out.

Outputs: data/fleet_daily.csv, data/fleet_by_minute.csv, figs/fleet.png
"""
import glob
import os

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

URBAN = {"1", "1א", "2", "3", "4", "5", "5א", "6", "6א", "10", "11", "15", "16", "80", "80א", "81", "82"}
AIRPORT = {"30", "30א", "31", "32", "50", "50א"}
LAYOVER = 20
INK, INK2, GRID, SURF = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"


def line_names():
    r = pd.read_csv("data/raw/gtfs_20261107/routes.txt", encoding="utf-8-sig")
    return dict(zip(r.route_id, r.route_short_name.astype(str), strict=True))


def rides(d, names):
    d = d.assign(line=d.siri_route__line_ref.map(names))
    d["group"] = np.where(d.line.isin(URBAN), "urban", np.where(d.line.isin(AIRPORT), "airport", "other"))
    unknown = d[d.line.isna()].siri_route__line_ref.nunique()
    g = d.groupby(["siri_ride__id", "siri_ride__vehicle_ref", "line", "group"]).recorded_at_time.agg(["min", "max", "size"])
    g = g[g["size"] >= 3].reset_index()  # a ride seen only once or twice can't give an interval
    return g, unknown


def minute_counts(g, day0):
    """Buses in service and in use for each minute of the service day."""
    mins = pd.date_range(day0, day0 + pd.Timedelta(hours=22), freq="1min", inclusive="left")
    svc = np.zeros(len(mins), int); use = np.zeros(len(mins), int)
    idx = lambda t: int((t - day0).total_seconds() // 60)  # noqa: E731
    for _, v in g.sort_values("min").groupby("siri_ride__vehicle_ref"):
        a = np.zeros(len(mins), bool); u = np.zeros(len(mins), bool)
        prev_end = None
        for r in v.itertuples():
            i, j = max(idx(r.min), 0), min(idx(r.max) + 1, len(mins))
            a[i:j] = True; u[i:j] = True
            if prev_end is not None and 0 < (r.min - prev_end).total_seconds() / 60 <= LAYOVER:
                u[max(idx(prev_end), 0):i] = True
            prev_end = r.max if prev_end is None else max(prev_end, r.max)
        svc += a; use += u
    return pd.DataFrame({"t": mins, "in_service": svc, "in_use": use})


def main():
    names = line_names()
    days, per_min = [], []
    for f in sorted(glob.glob("data/siri/*.parquet")):
        d = pd.read_parquet(f)
        if d.empty:
            continue
        day = os.path.basename(f)[:8]
        day0 = pd.Timestamp(f"{day[:4]}-{day[4:6]}-{day[6:]} 04:00", tz="Asia/Jerusalem")
        g, unknown = rides(d, names)
        for grp in ["urban", "airport"]:
            gg = g[g.group == grp]
            m = minute_counts(gg, day0)
            m["day"], m["group"] = day, grp
            per_min.append(m)
            days.append(dict(day=day, weekday=day0.day_name()[:3], group=grp, rides=len(gg),
                             vehicles=gg.siri_ride__vehicle_ref.nunique(),
                             peak_in_service=int(m.in_service.max()), peak_in_use=int(m.in_use.max()),
                             vehicle_hours_service=round(m.in_service.sum() / 60, 1),
                             vehicle_hours_use=round(m.in_use.sum() / 60, 1),
                             peak_time=m.t[m.in_use.idxmax()].tz_convert("Asia/Jerusalem").strftime("%H:%M"),
                             unknown_line_refs=unknown))
    t = pd.DataFrame(days)
    t.to_csv("data/fleet_daily.csv", index=False)
    pm = pd.concat(per_min)
    pm.to_csv("data/fleet_by_minute.csv", index=False)
    print(t.to_string(index=False))

    # chart: urban buses in use through the day, one line per weekday sample, by season
    u = pm[pm.group == "urban"].copy()
    u["hour"] = u.t.dt.tz_convert("Asia/Jerusalem")
    u["hod"] = u.hour.dt.hour + u.hour.dt.minute / 60
    u.loc[u.hod < 4, "hod"] += 24
    u["wd"] = pd.to_datetime(u.day).dt.dayofweek
    fig, ax = plt.subplots(figsize=(11, 4.2), dpi=150, facecolor=SURF)
    ax.set_facecolor(SURF)
    for (season, col) in [("2025-08", ORANGE), ("2025-12", BLUE), ("2026-02", AQUA)]:
        first = True
        for day, s in u[u.day.str.startswith(season.replace("-", "")) & u.wd.isin([6, 0, 1, 2, 3])].groupby("day"):
            s = s.set_index("hod").in_use.rolling(5, center=True, min_periods=1).mean()
            ax.plot(s.index, s.values, color=col, lw=1.2, alpha=.8, label=season if first else None)
            first = False
    ax.set_xticks(range(4, 27, 2)); ax.set_xticklabels([f"{h % 24:02d}:00" for h in range(4, 27, 2)], fontsize=8)
    ax.set_ylabel("urban buses in use", fontsize=9, color=INK2)
    ax.set_title("Eilat: urban buses in use at once, Sunday-Thursday (one line per day)", loc="left", fontsize=11)
    ax.spines[["top", "right"]].set_visible(False); ax.grid(axis="y", color=GRID); ax.legend(frameon=False, fontsize=8)
    fig.tight_layout(); os.makedirs("figs", exist_ok=True); fig.savefig("figs/fleet.png")


if __name__ == "__main__":
    main()
