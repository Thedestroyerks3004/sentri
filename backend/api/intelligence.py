from __future__ import annotations

from datetime import datetime, timedelta
from functools import lru_cache
from threading import RLock

import numpy as np
import pandas as pd
import pytz

from backend.api.services import DOW_NAMES, JUNCTION_SLUGS, store

IST = pytz.timezone("Asia/Kolkata")

# How long a computed briefing stays valid before being recomputed.
BRIEFING_CACHE_TTL_SECONDS = 60

# --- Short landmark label derived from the address string -----------------
# `location` in this dataset is always a full, already-geocoded postal
# address (e.g. "18th Main Road, Block 2, Koramangala, Bengaluru, Karnataka.
# Pin-560068 (India)") -- never a bare "lat, lon" string. The most specific,
# patrol-relevant part (street/landmark, then immediate area) is always the
# first one or two comma-separated segments; everything after that is city/
# state/pincode/country noise. So building a short landmark label is just
# trimming that string, not a reverse-geocoding problem -- no network call
# needed, no rate limit, no cold-start stall on startup.
ADDRESS_LANDMARK_SEGMENTS = 2

TIER_COLORS = {
    "Critical": "#dc2626",
    "High Risk": "#f97316",
    "Medium Risk": "#eab308",
    "Low Risk": "#22c55e",
}

JUNCTION_TO_SLUG = {v: k for k, v in JUNCTION_SLUGS.items() if k != "city"}


def _now_ist() -> datetime:
    return datetime.now(IST)


def _format_ampm(hour: int) -> str:
    h = int(hour) % 24
    if h == 0:
        return "12 AM"
    if h < 12:
        return f"{h} AM"
    if h == 12:
        return "12 PM"
    return f"{h - 12} PM"


def _peak_window(hour_series: pd.Series) -> str:
    if hour_series.empty:
        return "N/A"
    counts = hour_series.value_counts().to_dict()
    best_start, best_sum = 0, 0
    for h in range(24):
        s = sum(counts.get((h + i) % 24, 0) for i in range(3))
        if s > best_sum:
            best_sum, best_start = s, h
    end_h = (best_start + 2) % 24
    return f"{_format_ampm(best_start)} – {_format_ampm((end_h + 1) % 24)}"


def _patrol_action(risk_tier: str, predicted: float) -> str:
    if risk_tier == "Low Risk":
        return "Monitor remotely"
    if risk_tier == "Critical" and predicted > 30:
        return "Deploy 2 officers"
    if risk_tier in ("Critical", "High Risk") and predicted > 15:
        return "Deploy 1 officer"
    if risk_tier == "Critical":
        return "Deploy 2 officers"
    return "Deploy 1 officer"


def _predicted_today(
    loc_key: str,
    junction_name: str,
    peak_hour: int,
    zone_subset: pd.DataFrame | None = None,
) -> float:
    """
    `zone_subset`, when provided, is the already-filtered set of rows for
    this loc_key (e.g. from a lookup dict the caller built once). This
    avoids re-scanning the full store.violations frame per zone when the
    forecast fallback path is hit -- callers that already have the rows
    for this zone should pass them in.
    """
    slug = JUNCTION_TO_SLUG.get(junction_name)
    fc = store.forecasts.get(slug or "city", [])
    if fc:
        today_fc = fc[-24:]
        return round(float(np.mean([p["yhat"] for p in today_fc])), 0)
    sub = zone_subset if zone_subset is not None else store.violations[store.violations["loc_key"] == loc_key]
    if sub.empty:
        return 0.0
    daily = sub.groupby(sub["created_datetime"].dt.date).size()
    return round(float(daily.mean()), 0)


@lru_cache(maxsize=8)
def _historical_avg_for_day(day_name: str) -> float:
    """
    Historical day-of-week average violation count. This only changes
    when the underlying violations dataset changes (e.g. a new ingest),
    not minute to minute -- so it's cached independently of the 1-minute
    briefing TTL to avoid recomputing a groupby over the full history
    on every briefing refresh.
    """
    hist = store.violations[store.violations["day_of_week"] == day_name]
    hist_daily = hist.groupby(hist["created_datetime"].dt.date).size()
    return float(hist_daily.mean()) if not hist_daily.empty else 0.0


def _city_risk_level(day_idx: int) -> tuple[str, str, float, float, str]:
    city_fc = store.forecasts.get("city", [])
    predicted_today = float(np.sum([p["yhat"] for p in city_fc[-24:]])) if city_fc else 0
    day_name = DOW_NAMES[day_idx % 7]
    hist_avg = _historical_avg_for_day(day_name) or predicted_today or 1
    ratio = predicted_today / hist_avg if hist_avg else 1
    if ratio >= 1.2:
        label, color, icon = "CRITICAL", "#dc2626", "🔴"
    elif ratio >= 1.1:
        label, color, icon = "HIGH", "#f97316", "🟠"
    elif ratio >= 0.9:
        label, color, icon = "MEDIUM", "#eab308", "🟡"
    else:
        label, color, icon = "LOW", "#22c55e", "🟢"
    return label, color, predicted_today, ratio, icon


def _mode_or_default(series: pd.Series, default: str = "—") -> str:
    if series.empty:
        return default
    mode = series.mode(dropna=True)
    return str(mode.iloc[0]) if not mode.empty else default


def _zone_records(
    loc_key: str,
    subset: pd.DataFrame | dict[str, pd.DataFrame] | None = None,
) -> pd.DataFrame:
    if isinstance(subset, dict):
        return subset.get(loc_key, pd.DataFrame())
    df = subset if subset is not None else store.violations
    return df[df["loc_key"] == loc_key] if not df.empty else df


def _prepare_lookup(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    if df.empty:
        return {}
    return {loc: grp for loc, grp in df.groupby("loc_key", sort=False)}


def _looks_like_raw_coordinates(text: str) -> bool:
    """True if a string looks like 'lat, lon' rather than a real place name.

    Kept as a defensive fallback only -- this dataset's `location` column is
    always a full geocoded address (e.g. "18th Main Road, Block 2,
    Koramangala, Bengaluru, Karnataka. Pin-560068 (India)"), never a bare
    coordinate pair, so this should not trigger in practice. It guards
    against a future data source that might hand back raw coordinates.
    """
    if "," not in text:
        return False
    parts = [p.strip() for p in text.split(",")]
    if len(parts) != 2:
        return False
    try:
        float(parts[0])
        float(parts[1])
        return True
    except ValueError:
        return False


def _short_landmark_from_address(location: str, max_segments: int = ADDRESS_LANDMARK_SEGMENTS) -> str:
    """
    Derive a short, patrol-friendly landmark label from a full postal
    address by keeping just the first `max_segments` comma-separated
    parts -- typically the street/landmark name and immediate
    block/area -- and dropping the locality/city/state/pincode/country
    tail that follows. E.g.:

        "18th Main Road, Block 2, Koramangala, Bengaluru, Karnataka.
         Pin-560068 (India)"
        -> "18th Main Road, Block 2"

        "Dispensary Road, Tasker Town, Shivaji Nagar, Bengaluru,
         Karnataka. Pin-560001 (India)"
        -> "Dispensary Road, Tasker Town"

    No network call, no rate limit, no failure mode -- the landmark is
    already present in the address string, this just trims the noise.
    """
    parts = [p.strip() for p in location.split(",") if p.strip()]
    if not parts:
        return location
    return ", ".join(parts[:max_segments])


def _resolve_zone_name(junction: str, zone_meta: pd.Series) -> str:
    """
    Returns a human-readable zone name.

    Order of preference:
      1. `junction_name_clean`, when the point fell within the matching
         distance threshold of a known fixed junction at encoding time
         (i.e. it isn't the "No Junction" sentinel). This is the most
         specific, most trustworthy label available.
      2. A short landmark trimmed from the `location` address string,
         for points too far from any known junction to have been
         matched. The address already contains the landmark; this just
         keeps the first segment or two and drops the city/state/
         pincode/country tail.
      3. The raw `location` string as-is, only in the defensive case
         where it looks like a bare coordinate pair rather than an
         address (shouldn't occur with this dataset, but keeps the page
         from crashing if a future data source provides one).
    """
    if junction != "No Junction":
        return junction

    raw_location = str(zone_meta["location"])
    if _looks_like_raw_coordinates(raw_location):
        return raw_location

    return _short_landmark_from_address(raw_location)


def _build_zone_row(
    loc_key: str,
    zone_meta: pd.Series,
    filtered: pd.DataFrame | dict[str, pd.DataFrame] | None,
    priority: bool = False,
    filtered_lookup: dict[str, pd.DataFrame] | None = None,
    full_lookup: dict[str, pd.DataFrame] | None = None,
) -> dict:
    zv = _zone_records(loc_key, filtered_lookup if filtered_lookup is not None else filtered)
    count = len(zv)
    junction = "No Junction"
    top_violation = "—"
    top_vehicle = "—"
    peak_hour = 0
    if not zv.empty:
        jn = zv[zv["junction_name_clean"] != "No Junction"]["junction_name_clean"]
        junction = jn.mode().iloc[0] if not jn.empty else "No Junction"
        top_violation = _mode_or_default(zv["violation_type_parsed"])
        top_vehicle = _mode_or_default(zv["vehicle_type_clean"])
        peak_hour = int(zv["hour_int"].mode().iloc[0]) if not zv["hour_int"].empty else 0

    all_at_zone = _zone_records(
        loc_key,
        full_lookup if full_lookup is not None else store.violations,
    )
    peak_window = _peak_window(all_at_zone["hour_int"]) if not all_at_zone.empty else "N/A"
    predicted = _predicted_today(loc_key, junction, peak_hour, zone_subset=all_at_zone)
    risk = zone_meta["risk_tier"]
    station = zone_meta["police_station"]
    patrol_line = (
        f"Recommended patrol: {_format_ampm(max(0, peak_hour - 1))} – "
        f"{_format_ampm((peak_hour + 2) % 24)}, report to {station} station"
    )

    return {
        "loc_key": loc_key,
        "latitude": float(zone_meta["latitude"]),
        "longitude": float(zone_meta["longitude"]),
        "location": zone_meta["location"],
        "zone_name": _resolve_zone_name(junction, zone_meta),
        "risk_tier": risk,
        "risk_color": TIER_COLORS.get(risk, "#94a3b8"),
        "pcis": round(float(zone_meta["pcis"]), 1),
        "violations_at_hour": count,
        "total_violations": int(zone_meta["total_violations"]),
        "peak_window": peak_window,
        "peak_hour": peak_hour,
        "top_violation": top_violation,
        "top_vehicle": top_vehicle,
        "predicted_today": predicted,
        "police_station": station,
        "patrol_recommendation": patrol_line,
        "priority_patrol": priority,
        "action": _patrol_action(risk, predicted),
    }


@lru_cache(maxsize=128)
def get_patrol_map(
    hour: int,
    day: int,
    limit: int = 200,
    patrol_tonight: bool = False,
    search: str | None = None,
) -> dict:
    cap = min(max(int(limit), 1), 300)
    day_name = DOW_NAMES[day % 7]

    top_zones = (
        store.zones.dropna(subset=["latitude", "longitude"])
        .copy()
    )
    top_zones["latitude"] = top_zones["latitude"].astype(float)
    top_zones["longitude"] = top_zones["longitude"].astype(float)
    top_zones = top_zones[
        (top_zones["latitude"] != 0)
        & (top_zones["longitude"] != 0)
        & (top_zones["total_violations"] > 20)
    ]
    top_zones = top_zones.sort_values("pcis", ascending=False).head(300)

    if patrol_tonight:
        now = _now_ist()
        day_name = DOW_NAMES[now.weekday()]
        hours = [(now.hour + i) % 24 for i in range(3)]
        subset = store.violations[
            (store.violations["day_of_week"] == day_name)
            & (store.violations["hour_int"].isin(hours))
        ]
        mode_label = "patrol_tonight"
        active_hour = now.hour
    else:
        subset = store.violations[
            (store.violations["day_of_week"] == day_name)
            & (store.violations["hour_int"] == hour)
        ]
        mode_label = "manual"
        active_hour = hour

    if search:
        q = search.strip().lower()
        mask = (
            top_zones["location"].str.lower().str.contains(q, na=False, regex=False)
            | top_zones["police_station"].str.lower().str.contains(q, na=False)
        )
        # Only search junction names within violations belonging to zones
        # that already passed the eligibility filter (total_violations > 20),
        # rather than scanning the entire violations history for a
        # substring match -- the eligible-zone set is typically a small
        # fraction of all rows.
        eligible_keys = top_zones["loc_key"].dropna().astype(str).unique()
        eligible_violations = store.violations[store.violations["loc_key"].isin(eligible_keys)]
        junc_keys = eligible_violations[
            eligible_violations["junction_name_clean"].str.lower().str.contains(q, na=False, regex=False)
        ]["loc_key"].unique()
        top_zones = top_zones[mask | top_zones["loc_key"].isin(junc_keys)]

    top_keys = top_zones["loc_key"].dropna().astype(str).unique().tolist()
    candidate_df = store.violations[store.violations["loc_key"].isin(top_keys)]
    subset_for_top = subset[subset["loc_key"].isin(top_keys)] if not subset.empty else subset

    full_lookup = {loc: grp for loc, grp in candidate_df.groupby("loc_key", sort=False)}
    filtered_lookup = (
        {loc: grp for loc, grp in subset_for_top.groupby("loc_key", sort=False)}
        if not subset_for_top.empty else {}
    )

    markers = []
    for _, zone in top_zones.iterrows():
        row = _build_zone_row(
            zone["loc_key"],
            zone,
            subset,
            filtered_lookup=filtered_lookup,
            full_lookup=full_lookup,
        )
        if row["violations_at_hour"] <= 0 and not search:
            continue
        markers.append(row)

    markers.sort(key=lambda x: (x["pcis"], x["violations_at_hour"]), reverse=True)

    if patrol_tonight:
        for m in markers[:5]:
            m["priority_patrol"] = True

    capped_markers = markers[:cap]
    return {
        "mode": mode_label,
        "day": day_name,
        "hour": active_hour,
        "markers": capped_markers,
        "total_shown": len(capped_markers),
        "now_ist": _now_ist().strftime("%Y-%m-%d %H:%M IST"),
    }


@lru_cache(maxsize=256)
def get_zone_detail(loc_key: str) -> dict:
    zone = store.zones[store.zones["loc_key"] == loc_key]
    if zone.empty:
        return {"error": "Zone not found"}
    zone = zone.iloc[0]

    # Only need this one zone's rows -- a direct boolean filter is far
    # cheaper than grouping the entire violations history into a dict
    # just to pull out a single key. (Previously this did TWO full
    # groupbys over store.violations on every cache miss, which is the
    # likely cause of slow/timed-out responses on this endpoint.)
    zone_rows = store.violations[store.violations["loc_key"] == loc_key]
    single_lookup = {loc_key: zone_rows}

    row = _build_zone_row(
        loc_key,
        zone,
        zone_rows,
        filtered_lookup=single_lookup,
        full_lookup=single_lookup,
    )

    sub = zone_rows
    hourly = sub.groupby("hour_int").size().reset_index(name="count")
    daily_fc = []

    junction = row["zone_name"]
    slug = JUNCTION_TO_SLUG.get(junction, "city")
    fc = store.forecasts.get(slug, store.forecasts.get("city", []))
    if fc:
        daily_fc = [
            {"ds": p["ds"], "yhat": round(p["yhat"], 1)}
            for p in fc[-48:]
        ]

    return {**row, "hourly_pattern": hourly.to_dict(orient="records"), "forecast": daily_fc}


_daily_briefing_lock = RLock()


# ---------------------------------------------------------------------------
# CHANGED: this function used to be `@lru_cache(maxsize=1)` with NO
# arguments. Since it took no args, the cache key was always the same,
# so after the very first call the result was frozen forever -- "now",
# the risk level, live spikes, everything -- until the process restarted.
#
# Fix: accept a `_cache_bucket` string that changes every
# BRIEFING_CACHE_TTL_SECONDS. lru_cache then naturally treats each new
# bucket as a fresh cache key, so the briefing recomputes on a rolling
# basis instead of once per process lifetime. maxsize=8 keeps a small
# rolling window of recent buckets around instead of unbounded growth.
# ---------------------------------------------------------------------------
@lru_cache(maxsize=8)
def _compute_daily_briefing(_cache_bucket: int) -> dict:
    now = _now_ist()
    day_idx = now.weekday()
    day_name = DOW_NAMES[day_idx]
    risk_label, risk_color, predicted_city, risk_ratio, risk_icon = _city_risk_level(day_idx)

    max_date = store.violations["created_datetime"].max()
    week_start = max_date - timedelta(days=7)
    prev_week_start = max_date - timedelta(days=14)
    recent = store.violations[store.violations["created_datetime"] >= week_start]
    prev_week = store.violations[
        (store.violations["created_datetime"] >= prev_week_start)
        & (store.violations["created_datetime"] < week_start)
    ]

    current_hour = now.hour
    same_hour = store.violations[store.violations["hour_int"] == current_hour]
    active_hotspots = int(same_hour["loc_key"].nunique())

    vehicle_counts = recent.groupby("vehicle_number").size().rename("violations")
    repeat_vehicle_numbers = vehicle_counts[vehicle_counts >= 2].index
    repeat_flagged = int(repeat_vehicle_numbers.size)

    integrity_count = int(recent["is_anomaly"].sum())
    # 4 hours is always within the 7-day "recent" window, so filter from
    # that smaller frame instead of re-scanning all of store.violations.
    live_window = recent[recent["created_datetime"] >= now - timedelta(hours=4)]
    live_spikes = int(live_window["is_anomaly"].sum())
    anomalies = (
        recent[recent["is_anomaly"] == 1]
        .sort_values("anomaly_score", ascending=False)
        .head(5)
    )
    integrity_rows = []
    for _, a in anomalies.iterrows():
        atype = "Bulk filing burst" if a["same_second_filing_count"] > 5 else "Statistical anomaly"
        integrity_rows.append({
            "officer_id": a["created_by_id"],
            "station": a["police_station"],
            "anomaly_type": atype,
            "severity": round(float(a["anomaly_score"]), 3),
            "flagged_on": a["created_datetime"].strftime("%Y-%m-%d %H:%M"),
        })

    patrol_zones = []
    for hour in [current_hour, (current_hour + 1) % 24, (current_hour + 2) % 24]:
        sched = get_patrol_map(hour=hour, day=day_idx, limit=15, patrol_tonight=False)
        patrol_zones.extend(sched["markers"])

    # Rank by a clearer composite: predicted volume matters most (it's
    # the actual enforcement workload), violations_at_hour reflects live
    # activity right now, and pcis (already its own composite risk score)
    # breaks ties. The previous `pcis + violations_at_hour` summed two
    # differently-scaled numbers, which produced near-identical scores
    # across distinct zones and didn't actually differentiate rank order.
    def _zone_score(z: dict) -> tuple:
        return (z["predicted_today"], z["violations_at_hour"], z["pcis"])

    # Dedup on zone_name (the junction actually shown to the user), not
    # loc_key (a raw lat/lon point). Multiple loc_keys can map to the same
    # named junction -- e.g. several camera points at "Safina Plaza
    # Junction" -- and deduping on loc_key let all of them through as
    # "different" rows even though they displayed identically. Keep the
    # single best-scoring loc_key per junction name instead.
    seen_names: dict[str, dict] = {}
    for z in sorted(patrol_zones, key=_zone_score, reverse=True):
        name = z["zone_name"]
        if name not in seen_names or _zone_score(z) > _zone_score(seen_names[name]):
            seen_names[name] = z

    ranked = sorted(seen_names.values(), key=_zone_score, reverse=True)[:5]
    seen = {z["loc_key"] for z in ranked}
    seen_zone_names = {z["zone_name"] for z in ranked}

    if len(ranked) < 5:
        fallback_zones = store.zones.sort_values("pcis", ascending=False).head(20)
        fallback_keys = fallback_zones["loc_key"].dropna().astype(str).unique()
        fallback_violations = store.violations[store.violations["loc_key"].isin(fallback_keys)]
        zone_lookup = {loc: grp for loc, grp in fallback_violations.groupby("loc_key", sort=False)}
        for _, zone in fallback_zones.iterrows():
            if zone["loc_key"] in seen:
                continue
            row = _build_zone_row(
                zone["loc_key"],
                zone,
                fallback_violations,
                filtered_lookup=zone_lookup,
                full_lookup=zone_lookup,
            )
            # Same name-based dedup applies to fallback rows too.
            if row["zone_name"] in seen_zone_names:
                continue
            ranked.append(row)
            seen.add(zone["loc_key"])
            seen_zone_names.add(row["zone_name"])
            if len(ranked) >= 5:
                break

    patrol_table = []
    for i, z in enumerate(ranked, 1):
        badge = {"Critical": "🔴 Critical", "High Risk": "🟠 High", "Medium Risk": "🟡 Medium", "Low Risk": "🟢 Low"}
        patrol_table.append({
            "rank": i,
            "zone": z["zone_name"],
            "risk": badge.get(z["risk_tier"], z["risk_tier"]),
            "peak_window": z["peak_window"],
            "predicted_today": int(z["predicted_today"]),
            "violations_now": z["violations_at_hour"],
            "top_violation": z["top_violation"],
            "station": z["police_station"],
            "action": z["action"],
        })

    repeat_active = (
        recent.loc[recent["vehicle_number"].isin(repeat_vehicle_numbers)]
        .groupby("vehicle_number", sort=False)
        .agg(
            violations=("id", "count"),
            vehicle_type=("vehicle_type_clean", "first"),
            last_zone=("location", "last"),
            stations=("police_station", lambda s: ", ".join(sorted(s.unique()[:2]))),
        )
        .reset_index()
        .sort_values("violations", ascending=False)
        .head(10)
    )

    station_recent = (
        recent.groupby("police_station")
        .agg(
            filed=("id", "count"),
            approved=("validation_status_clean", lambda s: (s == "Approved").sum()),
            rejected=("validation_status_clean", lambda s: (s == "Rejected").sum()),
        )
        .reset_index()
    )
    station_prev = (
        prev_week.groupby("police_station")
        .agg(
            filed_prev=("id", "count"),
            rejected_prev=("validation_status_clean", lambda s: (s == "Rejected").sum()),
            approved_prev=("validation_status_clean", lambda s: (s == "Approved").sum()),
        )
        .reset_index()
    )
    station_recent["rejection_rate"] = station_recent.apply(
        lambda r: r["rejected"] / (r["approved"] + r["rejected"]) * 100
        if (r["approved"] + r["rejected"]) > 0 else 0,
        axis=1,
    )
    station_prev["rejection_rate_prev"] = station_prev.apply(
        lambda r: r["rejected_prev"] / (r["approved_prev"] + r["rejected_prev"]) * 100
        if (r["approved_prev"] + r["rejected_prev"]) > 0 else 0,
        axis=1,
    )
    stations = station_recent.merge(station_prev, on="police_station", how="left").fillna(0)
    stations["trend"] = stations.apply(
        lambda r: "↑" if r["rejection_rate"] > r["rejection_rate_prev"] + 1
        else ("↓" if r["rejection_rate"] < r["rejection_rate_prev"] - 1 else "→"),
        axis=1,
    )
    stations = stations.sort_values("rejection_rate", ascending=False)

    total_anomalies = int(store.violations["is_anomaly"].sum())

    return {
        "generated_at": now.strftime("%A, %d %B %Y — %H:%M IST"),
        "date": now.strftime("%Y-%m-%d"),
        "day": day_name,
        "time": now.strftime("%H:%M"),
        "city_risk_level": risk_label,
        "city_risk_color": risk_color,
        "city_risk_ratio": round(risk_ratio, 3),
        "city_risk_icon": risk_icon,
        "snapshot": {
            "predicted_today": int(predicted_city),
            "active_hotspots_now": active_hotspots,
            "repeat_offenders_week": repeat_flagged,
            "integrity_alerts_week": integrity_count,
            "live_spikes_4h": live_spikes,
            "wasted_enforcement_hours": int(store.meta.get("rejected_count", 0) * 15 / 60),
            "freshness": now.strftime("%Y-%m-%d %H:%M IST"),
        },
        "patrol_zones": patrol_table,
        "integrity_alerts": integrity_rows,
        "integrity_total": total_anomalies,
        "repeat_offenders_active": repeat_active.to_dict(orient="records"),
        "station_performance": stations.to_dict(orient="records"),
        "total_violation_records": int(len(store.violations)),
    }


def get_daily_briefing() -> dict:
    """
    Public entry point. Computes a time-bucket key that changes every
    BRIEFING_CACHE_TTL_SECONDS and passes it into the lru_cache'd compute
    function, so results stay fresh on a rolling ~1-minute basis rather
    than being frozen for the life of the process.
    """
    bucket = int(_now_ist().timestamp() // BRIEFING_CACHE_TTL_SECONDS)
    with _daily_briefing_lock:
        return _compute_daily_briefing(bucket)