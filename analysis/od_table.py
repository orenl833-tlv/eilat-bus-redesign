"""The trips the final checks draw from, as a table to read and sanity-check: origin, destination, time of day, and
each one's share of all bus trips that day (demand model, scripts/optimize_tt.py demand_od).
Usage: MODE=design PYTHONPATH=.:scripts:analysis python3 analysis/od_table.py   Output: data/od_table_<season>.csv
"""
import pandas as pd

import optimize_tt as X
from eilat import demand as Dm


def name_of():
    att = Dm.ATTRACTORS
    places = {(float(att.lat[i]), float(att.lon[i])): att.name[i] for i in att.index}
    m = X.MD.Model(); homes = m.pts[m.pts.kind == "home"]
    near = lambda o: int(homes.area.iloc[((homes.lat - o[0]) ** 2 + (homes.lon - o[1]) ** 2).argmin()])
    return lambda o: places.get(o) or f"home area {near(o)}"


def main():
    nm = name_of()
    for season in ("winter", "summer"):
        od = X.demand_od(season)
        rows = [(nm(o), nm(d), q, w) for o, ds in od.items() for d, _, ws in ds for q, w in ws.items() if w > 0]
        df = pd.DataFrame(rows, columns=["origin", "destination", "period", "trips_per_day"])
        df["share_pct"] = (100 * df.trips_per_day / df.trips_per_day.sum()).round(3)
        df["trips_per_day"] = df.trips_per_day.round(1)
        df.sort_values("share_pct", ascending=False).to_csv(f"data/od_table_{season}.csv", index=False)
        print(season, len(df), "rows")


if __name__ == "__main__":
    main()
