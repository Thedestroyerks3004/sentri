import time
import pandas as pd
from backend.api import services
from backend.api.intelligence import get_daily_briefing, get_patrol_map, _city_risk_level, _now_ist, DOW_NAMES

services.store.load()
now = _now_ist()
day_idx = now.weekday()
max_date = services.store.violations['created_datetime'].max()
week_start = max_date - pd.Timedelta(days=7)
prev_week_start = max_date - pd.Timedelta(days=14)
recent = services.store.violations[services.store.violations['created_datetime'] >= week_start]
prev_week = services.store.violations[
    (services.store.violations['created_datetime'] >= prev_week_start)
    & (services.store.violations['created_datetime'] < week_start)
]

steps = []

start = time.perf_counter()
_city_risk_level(day_idx)
steps.append(('risk', time.perf_counter() - start))

start = time.perf_counter()
same_hour = services.store.violations[services.store.violations['hour_int'] == now.hour]
active_hotspots = int(same_hour['loc_key'].nunique())
steps.append(('same_hour', time.perf_counter() - start, active_hotspots))

start = time.perf_counter()
repeat_week = (
    recent.groupby('vehicle_number')
    .filter(lambda g: len(g) >= 2)
    .groupby('vehicle_number')
    .size()
)
steps.append(('repeat_week', time.perf_counter() - start, len(repeat_week)))

start = time.perf_counter()
integrity_count = int(recent['is_anomaly'].sum())
live_window = services.store.violations[
    services.store.violations['created_datetime'] >= now - pd.Timedelta(hours=4)
]
live_spikes = int(live_window['is_anomaly'].sum())
anomalies = (
    recent[recent['is_anomaly'] == 1]
    .sort_values('anomaly_score', ascending=False)
    .head(5)
)
steps.append(('anomaly_setup', time.perf_counter() - start, len(anomalies), integrity_count, live_spikes))

start = time.perf_counter()
patrol_zones = []
for hour in [now.hour, (now.hour + 1) % 24, (now.hour + 2) % 24]:
    sched = get_patrol_map(hour=hour, day=day_idx, limit=15, patrol_tonight=False)
    patrol_zones.extend(sched['markers'])
seen = set()
ranked = []
for z in sorted(patrol_zones, key=lambda x: x['pcis'] + x['violations_at_hour'], reverse=True):
    if z['loc_key'] in seen:
        continue
    seen.add(z['loc_key'])
    ranked.append(z)
    if len(ranked) >= 5:
        break
steps.append(('patrol_rank', time.perf_counter() - start, len(ranked), len(patrol_zones)))

start = time.perf_counter()
repeat_active = (
    recent.groupby('vehicle_number')
    .agg(
        violations=('id', 'count'),
        vehicle_type=('vehicle_type_clean', 'first'),
        last_zone=('location', 'last'),
        stations=('police_station', lambda s: ', '.join(sorted(s.unique()[:2]))),
    )
    .reset_index()
    .query('violations >= 2')
    .sort_values('violations', ascending=False)
    .head(10)
)
steps.append(('repeat_active', time.perf_counter() - start, len(repeat_active)))

start = time.perf_counter()
station_recent = (
    recent.groupby('police_station')
    .agg(
        filed=('id', 'count'),
        approved=('validation_status_clean', lambda s: (s == 'Approved').sum()),
        rejected=('validation_status_clean', lambda s: (s == 'Rejected').sum()),
    )
    .reset_index()
)
station_prev = (
    prev_week.groupby('police_station')
    .agg(
        filed_prev=('id', 'count'),
        rejected_prev=('validation_status_clean', lambda s: (s == 'Rejected').sum()),
        approved_prev=('validation_status_clean', lambda s: (s == 'Approved').sum()),
    )
    .reset_index()
)
steps.append(('station_precompute', time.perf_counter() - start, len(station_recent), len(station_prev)))

start = time.perf_counter()
station_recent['rejection_rate'] = station_recent.apply(
    lambda r: r['rejected'] / (r['approved'] + r['rejected']) * 100
    if (r['approved'] + r['rejected']) > 0 else 0,
    axis=1,
)
station_prev['rejection_rate_prev'] = station_prev.apply(
    lambda r: r['rejected_prev'] / (r['approved_prev'] + r['rejected_prev']) * 100
    if (r['approved_prev'] + r['rejected_prev']) > 0 else 0,
    axis=1,
)
stations = station_recent.merge(station_prev, on='police_station', how='left').fillna(0)
stations['trend'] = stations.apply(
    lambda r: '↑' if r['rejection_rate'] > r['rejection_rate_prev'] + 1
    else ('↓' if r['rejection_rate'] < r['rejection_rate_prev'] - 1 else '→'),
    axis=1,
)
stations = stations.sort_values('rejection_rate', ascending=False)
steps.append(('station_merge', time.perf_counter() - start, len(stations)))

start = time.perf_counter()
result = get_daily_briefing()
steps.append(('daily_briefing_fn', time.perf_counter() - start, len(result['patrol_zones']), len(result['integrity_alerts'])))

for item in steps:
    print(item)
