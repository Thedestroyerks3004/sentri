from __future__ import annotations

from datetime import datetime, timedelta
from functools import lru_cache

import numpy as np
import pandas as pd
import pytz

from api.services import DOW_NAMES, JUNCTION_SLUGS, store

IST = pytz.timezone("Asia/Kolkata")

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


def _predicted_today(loc_key: str, junction_name: str, peak_hour: int) -> float:
    slug = JUNCTION_TO_SLUG.get(junction_name)
    fc = store.forecasts.get(slug or "city", [])
    if fc:
        today_fc = fc[-24:]
        return round(float(np.mean([p["yhat"] for p in today_fc])), 0)
    sub = store.violations[store.violations["loc_key"] == loc_key]
    if sub.empty:
        return 0.0
    daily = sub.groupby(sub["created_datetime"].dt.date).size()
    return round(float(daily.mean()), 0)


def _city_risk_level(day_idx: int) -> tuple[str, str, float, float, str]:
    city_fc = store.forecasts.get("city", [])
    predicted_today = float(np.sum([p["yhat"] for p in city_fc[-24:]])) if city_fc else 0
    day_name = DOW_NAMES[day_idx % 7]
    hist = store.violations[store.violations["day_of_week"] == day_name]
    hist_daily = hist.groupby(hist["created_datetime"].dt.date).size()
    hist_avg = float(hist_daily.mean()) if not hist_daily.empty else predicted_today or 1
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
        junction = jn.mode().iloc[0] if not jn.empty else zv["location"].iloc[0][:80]
        top_violation = _mode_or_default(zv["violation_type_parsed"])
        top_vehicle = _mode_or_default(zv["vehicle_type_clean"])
        peak_hour = int(zv["hour_int"].mode().iloc[0]) if not zv["hour_int"].empty else 0

    all_at_zone = _zone_records(
        loc_key,
        full_lookup if full_lookup is not None else store.violations,
    )
    peak_window = _peak_window(all_at_zone["hour_int"]) if not all_at_zone.empty else "N/A"
    predicted = _predicted_today(loc_key, junction, peak_hour)
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
        "zone_name": junction if junction != "No Junction" else zone_meta["location"][:80],
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
    top_zones = top_zones[
        (top_zones["latitude"].astype(float).fillna(0) != 0)
        & (top_zones["longitude"].astype(float).fillna(0) != 0)
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
            top_zones["location"].str.lower().str.contains(q, na=False)
            | top_zones["police_station"].str.lower().str.contains(q, na=False)
        )
        junc_keys = store.violations[
            store.violations["junction_name_clean"].str.lower().str.contains(q, na=False)
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
    row = _build_zone_row(
        loc_key,
        zone,
        store.violations,
        filtered_lookup={loc: grp for loc, grp in store.violations.groupby("loc_key", sort=False)},
        full_lookup={loc: grp for loc, grp in store.violations.groupby("loc_key", sort=False)},
    )

    sub = _zone_records(loc_key)
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


@lru_cache(maxsize=1)
def get_daily_briefing() -> dict:
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

    repeat_week = (
        recent.groupby("vehicle_number")
        .filter(lambda g: len(g) >= 2)
        .groupby("vehicle_number")
        .size()
    )
    repeat_flagged = int(len(repeat_week))

    integrity_count = int(recent["is_anomaly"].sum())
    live_window = store.violations[
        store.violations["created_datetime"] >= now - timedelta(hours=4)
    ]
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
    seen = set()
    ranked = []
    for z in sorted(patrol_zones, key=lambda x: x["pcis"] + x["violations_at_hour"], reverse=True):
        if z["loc_key"] in seen:
            continue
        seen.add(z["loc_key"])
        ranked.append(z)
        if len(ranked) >= 5:
            break

    if len(ranked) < 5:
        zone_lookup = {loc: grp for loc, grp in store.violations.groupby("loc_key", sort=False)}
        for _, zone in store.zones.sort_values("pcis", ascending=False).head(20).iterrows():
            if zone["loc_key"] in seen:
                continue
            row = _build_zone_row(
                zone["loc_key"],
                zone,
                store.violations,
                filtered_lookup=zone_lookup,
                full_lookup=zone_lookup,
            )
            ranked.append(row)
            seen.add(zone["loc_key"])
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
            "station": z["police_station"],
            "action": z["action"],
        })

    repeat_active = (
        recent.groupby("vehicle_number")
        .agg(
            violations=("id", "count"),
            vehicle_type=("vehicle_type_clean", "first"),
            last_zone=("location", "last"),
            stations=("police_station", lambda s: ", ".join(sorted(s.unique()[:2]))),
        )
        .reset_index()
        .query("violations >= 2")
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
    }
