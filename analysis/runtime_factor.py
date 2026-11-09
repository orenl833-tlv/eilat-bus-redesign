"""Real run time vs planned, by line and period. A SIRI ride often starts reporting while the bus still stands
at the first stop, and keeps reporting after arrival, so leading/trailing reports at < 3 km/h are trimmed, then
1 minute is added for the reporting interval (~60 s). Planned = GTFS 10 Nov 2026."""
import pandas as pd

r = pd.read_csv('data/raw/gtfs_20261107/routes.txt', encoding='utf-8-sig')
names = dict(zip(r.route_id, r.route_short_name.astype(str)))
DAYS = ['20251207', '20251209', '20251210', '20251211', '20260215', '20260217', '20260218']
P = {'06-09': (6, 9), '09-12': (9, 12), '12-15': (12, 15), '15-19': (15, 19), '19-24': (19, 24)}
per = lambda h: next((k for k, (a, b) in P.items() if a <= h < b), None)  # noqa: E731
rows = []
for day in DAYS:
    d = pd.read_parquet(f'data/siri/{day}.parquet')
    d['line'] = d.siri_route__line_ref.map(names).astype(str).str.replace('א', '')
    d = d[d.line.isin(['1', '2', '3', '4', '5', '6', '15', '16'])].sort_values(['siri_ride__id', 'recorded_at_time'])
    for rid, g in d.groupby('siri_ride__id'):
        mv = g.velocity.values >= 3
        if mv.sum() < 8:
            continue
        i0, i1 = mv.argmax(), len(mv) - 1 - mv[::-1].argmax()
        g = g.iloc[max(i0 - 1, 0): i1 + 2]
        dur = (g.recorded_at_time.iloc[-1] - g.recorded_at_time.iloc[0]).total_seconds() / 60 + 1
        sched = pd.to_datetime(g.siri_ride__scheduled_start_time.iloc[0], utc=True, format='ISO8601')
        late = (g.recorded_at_time.iloc[0] - sched).total_seconds() / 60
        rows.append(dict(line=g.line.iloc[0], period=per(sched.tz_convert('Asia/Jerusalem').hour), actual=dur,
                         start_delay=late, untrimmed=(d[d.siri_ride__id == rid].recorded_at_time.agg(['min', 'max']).diff().iloc[-1].total_seconds() / 60)))
t = pd.DataFrame(rows)
st = pd.read_csv('data/gtfs_eilat/stop_times.csv'); tr = pd.read_csv('data/gtfs_eilat/trips.csv').merge(
    pd.read_csv('data/gtfs_eilat/routes.csv')[['route_id', 'route_short_name']], on='route_id')
tr['line'] = tr.route_short_name.astype(str).str.replace('א', '')
p = st.groupby('trip_id').agg(t0=('dep', 'min'), t1=('arr', 'max')).join(tr.set_index('trip_id').line)
p['plan'] = (p.t1 - p.t0) / 60; p['period'] = (p.t0 // 3600).map(per)
a = t.groupby(['line', 'period']).actual.median(); b = p.groupby(['line', 'period']).plan.median()
f = (a / b).dropna()
print('actual (trimmed) / planned:'); print(f.unstack().round(2).to_string())
print('median factor', round(f.median(), 2), '| median minutes trimmed per ride',
      round((t.untrimmed + 1 - t.actual).median(), 1), '| median start vs schedule (min)', round(t.start_delay.median(), 1))
f.rename('factor').reset_index().to_csv('data/runtime_factor.csv', index=False)
