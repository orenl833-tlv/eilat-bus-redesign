"""Fetch every SIRI bus report in and around Eilat for whole service days (Open Bus Stride).

Box: Eilat plus Ramon airport (line 30). A day runs 04:00 to 02:00 next day, Israel time. Output:
data/siri/YYYYMMDD.parquet, one row per report. Resumable: days already saved are skipped.

Usage: python3 scripts/fetch_siri.py 2025-12-07 2025-12-08 ...
"""
import datetime as dt
import json
import os
import sys
import time
import urllib.parse
import urllib.request

import pandas as pd

API = "https://open-bus-stride-api.hasadna.org.il/siri_vehicle_locations/list"
BOX = {"lat__greater_or_equal": 29.45, "lat__lower_or_equal": 29.76,
       "lon__greater_or_equal": 34.85, "lon__lower_or_equal": 35.10}
FIELDS = ["id", "recorded_at_time", "lon", "lat", "bearing", "velocity", "distance_from_journey_start",
          "siri_route__line_ref", "siri_route__operator_ref", "siri_ride__id", "siri_ride__vehicle_ref",
          "siri_ride__scheduled_start_time", "siri_ride__gtfs_ride_id"]
TZ = dt.timezone(dt.timedelta(0))


def get(params, retries=5):
    url = API + "?" + urllib.parse.urlencode(params)
    for i in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=180) as r:
                return json.load(r)
        except Exception as e:  # noqa: BLE001
            print("retry", i, e, flush=True)
            time.sleep(2 ** (i + 1))
    raise RuntimeError(url)


def fetch_day(day):
    start = pd.Timestamp(f"{day} 04:00", tz="Asia/Jerusalem").tz_convert("UTC")
    end = start + pd.Timedelta(hours=22)
    rows, t = [], start
    while t < end:
        t2 = min(t + pd.Timedelta(hours=2), end)
        offset = 0
        while True:
            page = get({"recorded_at_time_from": t.isoformat(), "recorded_at_time_to": t2.isoformat(),
                        "limit": 10000, "offset": offset, "order_by": "id asc", **BOX})
            rows += [{k: r.get(k) for k in FIELDS} for r in page]
            if len(page) < 10000:
                break
            offset += 10000
        t = t2
        time.sleep(.3)
    d = pd.DataFrame(rows, columns=FIELDS).drop_duplicates("id")
    d["recorded_at_time"] = pd.to_datetime(d.recorded_at_time, utc=True, format="ISO8601")
    return d


def main(days):
    os.makedirs("data/siri", exist_ok=True)
    for day in days:
        out = f"data/siri/{day.replace('-', '')}.parquet"
        if os.path.exists(out):
            continue
        d = fetch_day(day)
        d.to_parquet(out)
        print(day, len(d), d.siri_ride__vehicle_ref.nunique(), "vehicles", flush=True)


if __name__ == "__main__":
    main(sys.argv[1:])
