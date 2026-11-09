"""How much time does a bus stop cost in Eilat? Decompose real trip times (SIRI) into: dwell (speed < 3 km/h
within 35 m of a stop), stopped elsewhere (traffic lights, junctions), and slowing/accelerating (moving time
beyond what the trip would take at cruising speed). Cruising speed = 75th percentile of the ride's speeds
away from stops. Days: school-term weekdays without feed gaps (Dec 2025, Feb 2026)."""
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

r = pd.read_csv('data/raw/gtfs_20261107/routes.txt', encoding='utf-8-sig')
names = dict(zip(r.route_id, r.route_short_name.astype(str)))
URB = {'1', '1א', '2', '3', '4', '5', '5א', '6', '6א', '15', '16'}
stops = pd.read_csv('data/gtfs_eilat/stops.csv')
MX, MY = 111320 * np.cos(np.radians(29.55)), 110850
tree = cKDTree(np.c_[stops.stop_lon.values * MX, stops.stop_lat.values * MY])
DAYS = ['20251207', '20251209', '20251210', '20251211', '20260215', '20260217', '20260218']
rows = []
for day in DAYS:
    d = pd.read_parquet(f'data/siri/{day}.parquet')
    d['line'] = d.siri_route__line_ref.map(names); d = d[d.line.isin(URB)].copy()
    dist, _ = tree.query(np.c_[d.lon * MX, d.lat * MY]); d['near'] = dist < 35
    d = d.sort_values(['siri_ride__id', 'recorded_at_time'])
    for rid, g in d.groupby('siri_ride__id'):
        if len(g) < 15:
            continue
        dur = (g.recorded_at_time.iloc[-1] - g.recorded_at_time.iloc[0]).total_seconds()
        dd = g.distance_from_journey_start.iloc[-1] - g.distance_from_journey_start.iloc[0]
        v = g.velocity.clip(upper=90)
        rows.append(dict(line=g.line.iloc[0].replace('א', ''), dur=dur, dist=dd, hour=g.recorded_at_time.iloc[0].tz_convert('Asia/Jerusalem').hour,
                         dwell=((v < 3) & g.near).mean(), other=((v < 3) & ~g.near).mean(),
                         v_cruise=v[(v > 10) & ~g.near].quantile(.75)))
t = pd.DataFrame(rows); t = t[(t.dist > 2000) & (t.dur > 600)].copy()
t['dwell_s'] = t.dwell * t.dur; t['other_s'] = t.other * t.dur
t['free_s'] = t.dist / (t.v_cruise / 3.6)
t['accdec_s'] = (t.dur - t.dwell_s - t.other_s - t.free_s).clip(lower=0)
st = pd.read_csv('data/gtfs_eilat/stop_times.csv'); tr = pd.read_csv('data/gtfs_eilat/trips.csv').merge(
    pd.read_csv('data/gtfs_eilat/routes.csv')[['route_id', 'route_short_name']], on='route_id')
tr['line'] = tr.route_short_name.astype(str).str.replace('א', '')
nst = st.groupby('trip_id').size().rename('nst').to_frame().join(tr.set_index('trip_id').line).groupby('line').nst.median()
t['nst'] = t.line.map(nst)
g = t.groupby('line')[['dur', 'dist', 'v_cruise', 'dwell_s', 'other_s', 'accdec_s', 'nst']].median()
g['rides'] = t.groupby('line').size()
share = g.dwell_s / (g.dwell_s + g.other_s)
g['per_sched_stop_s'] = (g.dwell_s + g.accdec_s * share) / g.nst
print(f'{len(t)} rides'); print(g.round(1).to_string())
m = t[['dur', 'dwell_s', 'other_s', 'accdec_s', 'free_s']].median()
print('median ride: ' + ', '.join(f'{k} {v:.0f}s' for k, v in m.items()))
tot_stop = (t.dwell_s + t.accdec_s * t.dwell_s / (t.dwell_s + t.other_s).clip(lower=1)) / t.nst
print(f'time per scheduled stop, all rides: median {tot_stop.median():.0f}s, IQR {tot_stop.quantile(.25):.0f}-{tot_stop.quantile(.75):.0f}s')
# per stop actually served: estimate the share of scheduled stops where the bus stops = dwell events / stops
print('cruise speed median %.0f km/h' % t.v_cruise.median())
t.to_csv('data/stop_cost_rides.csv', index=False)
