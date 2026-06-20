from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS = ROOT / "artifacts"
FORECAST_DIR = ARTIFACTS / "forecasts"

NIGHT_BUCKETS = ["Late Night (12AM-6AM)", "Night (10PM-12AM)"]
NIGHT_HOURS = set(range(0, 6)) | {22, 23}

DOW_NAMES = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]

JUNCTION_SLUGS = {
    "city": "City-wide",
    "safina_plaza": "BTP051 - Safina Plaza Junction",
    "kr_market": "BTP082 - KR Market Junction",
    "elite": "BTP040 - Elite Junction",
    "sagar_theatre": "BTP044 - Sagar Theatre Junction",
    "central_street": "BTP211 - Central Street Junction",
}


class DataStore:
    def __init__(self) -> None:
        self.violations: pd.DataFrame = pd.DataFrame()
        self.zones: pd.DataFrame = pd.DataFrame()
        self.meta: dict = {}
        self.forecasts: dict[str, list] = {}
        self.summary_cache: dict = {}
        self.repeat_offenders_cache: dict = {}
        self.station_cache: dict = {}
        self.feedback_cache: dict = {}

    def load(self) -> None:
        self.violations = pd.read_parquet(ARTIFACTS / "violations_scored.parquet")
        self.violations["created_datetime"] = pd.to_datetime(
            self.violations["created_datetime"], utc=True
        )
        self.zones = pd.read_parquet(ARTIFACTS / "zone_risk.parquet")
        with open(ARTIFACTS / "meta.json") as f:
            self.meta = json.load(f)
        for path in FORECAST_DIR.glob("*.json"):
            if path.name == "index.json":
                continue
            with open(path) as f:
                self.forecasts[path.stem] = json.load(f)

        # Keep caches empty until a request actually needs them.
        # This keeps startup lighter and avoids precomputing large summaries
        # for every endpoint before the app is ready to serve traffic.
        self.summary_cache = {}
        self.repeat_offenders_cache = {}
        self.station_cache = {}
        self.feedback_cache = {}


store = DataStore()


def warm_caches() -> None:
    """Precompute the most-used responses once the data store is ready."""
    if store.violations.empty or store.zones.empty:
        return
    store.summary_cache = get_summary()
    store.repeat_offenders_cache = get_repeat_offenders()
    store.station_cache = get_station_performance()
    store.feedback_cache = get_feedback_loop()

    # These endpoints are expensive on first request because they build large
    # summary objects over the full dataset. Precompute them once at startup so
    # the first dashboard load avoids waiting on a cold cache.
    from backend.api.intelligence import get_daily_briefing, get_patrol_map

    get_daily_briefing()
    get_patrol_map(hour=5, day=0, limit=50, patrol_tonight=False)


def rejection_rate(series: pd.Series) -> float:
    approved = (series == "Approved").sum()
    rejected = (series == "Rejected").sum()
    total = approved + rejected
    return float(rejected / total * 100) if total else 0.0


def get_summary() -> dict:
    if store.summary_cache:
        return store.summary_cache
    df = store.violations
    total = len(df)
    night = int(df["is_night"].sum())
    bulk = int(df["is_bulk_filed"].sum())
    rejected = int((df["validation_status_clean"] == "Rejected").sum())
    repeat = int((df.groupby("vehicle_number").size() >= 5).sum())
    hotspots = int((store.zones["risk_tier"] == "Critical").sum())
    rej_rate = rejection_rate(df["validation_status_clean"])
    wasted_hours = round(rejected * 15 / 60)

    result = {
        "total_violations": total,
        "night_violations": night,
        "night_pct": round(night / total * 100, 1),
        "bulk_filed": bulk,
        "bulk_pct": round(bulk / total * 100, 1),
        "rejection_rate": round(rej_rate, 1),
        "repeat_offenders": repeat,
        "active_hotspots": hotspots,
        "rejected_count": rejected,
        "wasted_enforcement_hours": wasted_hours,
        "max_same_second_burst": int(store.meta.get("max_same_second", 61)),
        "anomaly_count": int(df["is_anomaly"].sum()),
        "anomaly_pct": round(float(df["is_anomaly"].mean() * 100), 1),
        "hero": {
            "wasted_hours": wasted_hours,
            "burst_record": int(store.meta.get("max_same_second", 61)),
            "invalid_ratio": "1 in 3",
        },
    }
    store.summary_cache = result
    return result


def get_hotspots(risk_tier: str | None = None, limit: int = 500) -> list[dict]:
    zones = store.zones.sort_values("pcis", ascending=False)
    if risk_tier:
        zones = zones[zones["risk_tier"].str.lower() == risk_tier.lower()]
    cols = [
        "loc_key", "latitude", "longitude", "location", "police_station",
        "total_violations", "night_violations", "pcis", "risk_tier",
    ]
    return zones[cols].head(limit).to_dict(orient="records")


def get_junctions(limit: int = 50) -> list[dict]:
    df = store.violations
    junctions = df[df["junction_name_clean"] != "No Junction"].copy()
    if junctions.empty:
        return []
    agg = (
        junctions.groupby(["junction_name_clean", "latitude", "longitude"], as_index=False)
        .agg(violation_count=("id", "count"), peak_hour=("hour_int", "median"))
        .sort_values("violation_count", ascending=False)
        .head(limit)
    )
    return agg.to_dict(orient="records")


def get_anomalies(min_score: float = 0.0, limit: int = 500) -> list[dict]:
    df = store.violations[store.violations["is_anomaly"] == 1].copy()
    if min_score > 0:
        threshold = df["anomaly_score"].quantile(1 - min_score) if min_score < 1 else df["anomaly_score"].max()
        df = df[df["anomaly_score"] >= threshold]
    df = df.sort_values("anomaly_score", ascending=False).head(limit)
    cols = [
        "id", "latitude", "longitude", "location", "created_datetime",
        "created_by_id", "police_station", "anomaly_score", "is_anomaly",
        "same_second_filing_count", "violation_type_parsed",
    ]
    records = df[cols].to_dict(orient="records")
    for r in records:
        if hasattr(r.get("created_datetime"), "isoformat"):
            r["created_datetime"] = r["created_datetime"].isoformat()
    return records


def get_forecast(location: str) -> dict:
    key = location.lower().replace(" ", "_").replace("-", "_")
    if key not in store.forecasts:
        for slug in JUNCTION_SLUGS:
            if location.lower() in slug or location.lower() in JUNCTION_SLUGS[slug].lower():
                key = slug
                break
    if key not in store.forecasts:
        return {"location": location, "forecast": [], "error": "Location not found"}

    forecast_rows = store.forecasts[key]
    for row in forecast_rows:
        if "yhat_lower" not in row and "yhat_upper" not in row:
            continue

    return {
        "location": key,
        "label": JUNCTION_SLUGS.get(key, key),
        "forecast": forecast_rows,
    }


def get_commercial_impact() -> dict:
    path = ARTIFACTS / "commercial_impact.json"
    if not path.exists():
        return {"error": "commercial impact artifact not found"}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def get_offender_fingerprint() -> dict:
    path = ARTIFACTS / "offender_fingerprint.json"
    if not path.exists():
        return {"error": "offender fingerprint artifact not found"}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def get_scheduler(hour: int, day: int, limit: int = 10) -> list[dict]:
    day_name = DOW_NAMES[day % 7]
    df = store.violations[
        (store.violations["hour_int"] == hour)
        & (store.violations["day_of_week"] == day_name)
    ]
    if df.empty:
        return []

    zones = (
        df.groupby(["loc_key", "latitude", "longitude", "location", "police_station"], as_index=False)
        .agg(
            historical_violations=("id", "count"),
            avg_anomaly=("anomaly_score", "mean"),
            bulk_share=("is_bulk_filed", "mean"),
        )
    )
    zones = zones.merge(
        store.zones[["loc_key", "pcis", "risk_tier"]],
        on="loc_key",
        how="left",
    )
    zones["pcis"] = zones["pcis"].fillna(0)
    zones["risk_tier"] = zones["risk_tier"].fillna("Low Risk")

    mx = zones["historical_violations"].max() or 1
    zones["priority_score"] = (
        (zones["historical_violations"] / mx) * 0.45
        + (zones["pcis"] / 100) * 0.35
        + zones["bulk_share"] * 0.10
        + (zones["avg_anomaly"] / (zones["avg_anomaly"].max() or 1)) * 0.10
    ) * 100

    city_fc = store.forecasts.get("city", [])
    if city_fc:
        zones["predicted_violations"] = round(
            float(np.mean([p["yhat"] for p in city_fc[:24]])), 1
        )
    else:
        zones["predicted_violations"] = 0

    ranked = zones.sort_values("priority_score", ascending=False).head(limit)
    return ranked.to_dict(orient="records")


def get_vehicle(vehicle_number: str) -> dict:
    mask = store.violations["vehicle_number"].str.upper() == vehicle_number.strip().upper()
    hist = store.violations[mask].sort_values("created_datetime", ascending=False)
    if hist.empty:
        return {"vehicle_number": vehicle_number, "violations": [], "count": 0}
    cols = [
        "id", "created_datetime", "latitude", "longitude", "location",
        "violation_type_parsed", "police_station", "validation_status_clean",
        "hour_int", "day_of_week",
    ]
    records = hist[cols].to_dict(orient="records")
    for r in records:
        if hasattr(r.get("created_datetime"), "isoformat"):
            r["created_datetime"] = r["created_datetime"].isoformat()
    return {
        "vehicle_number": vehicle_number.upper(),
        "count": len(records),
        "violations": records,
    }


def get_night_paradox() -> dict:
    df = store.violations
    hourly = df.groupby("hour_int").size().reset_index(name="violations")
    hourly["period"] = hourly["hour_int"].apply(lambda h: "Night" if h in NIGHT_HOURS else "Day")

    order = [
        "Late Night (12AM-6AM)", "Morning (6AM-10AM)", "Midday (10AM-2PM)",
        "Afternoon (2PM-6PM)", "Evening (6PM-10PM)", "Night (10PM-12AM)",
    ]
    buckets = df["time_bucket"].value_counts().reindex(order).fillna(0).reset_index()
    buckets.columns = ["time_bucket", "count"]

    heatmap = df.groupby(["day_of_week", "hour_int"]).size().reset_index(name="violations")
    vehicles = df.groupby(["is_night", "vehicle_category"]).size().reset_index(name="count")

    peak = hourly.loc[hourly["violations"].idxmax()]
    return {
        "hourly": hourly.to_dict(orient="records"),
        "buckets": buckets.to_dict(orient="records"),
        "heatmap": heatmap.to_dict(orient="records"),
        "vehicles": vehicles.to_dict(orient="records"),
        "peak_hour": int(peak["hour_int"]),
        "peak_count": int(peak["violations"]),
    }


def get_bulk_filing() -> dict:
    df = store.violations
    daily = (
        df.groupby(df["created_datetime"].dt.date)
        .agg(total=("id", "count"), bulk=("is_bulk_filed", "sum"))
        .reset_index()
    )
    daily.columns = ["date", "total", "bulk"]
    daily["bulk_pct"] = daily["bulk"] / daily["total"] * 100
    daily["date"] = daily["date"].astype(str)

    bulk = df[df["same_second_filing_count"] > 1]
    events = (
        bulk.groupby(["created_datetime", "location", "created_by_id", "police_station"], as_index=False)
        .agg(count=("id", "count"), same_second=("same_second_filing_count", "max"))
        .sort_values(["same_second", "count"], ascending=False)
        .head(20)
    )
    events["created_datetime"] = events["created_datetime"].astype(str)

    officers = (
        df.groupby("created_by_id")
        .agg(total=("id", "count"), bulk=("is_bulk_filed", "sum"), police_station=("police_station", "first"))
        .reset_index()
    )
    officers = officers[officers["total"] >= 50]
    officers["bulk_pct"] = officers["bulk"] / officers["total"] * 100
    officers = officers.sort_values("bulk_pct", ascending=False).head(20)

    return {
        "timeline": daily.to_dict(orient="records"),
        "events": events.to_dict(orient="records"),
        "officers": officers.to_dict(orient="records"),
        "max_burst": int(df["same_second_filing_count"].max()),
    }


def get_station_performance() -> dict:
    if store.station_cache:
        return store.station_cache
    df = store.violations
    stations = (
        df.groupby("police_station")
        .agg(
            total=("id", "count"),
            approved=("validation_status_clean", lambda s: (s == "Approved").sum()),
            rejected=("validation_status_clean", lambda s: (s == "Rejected").sum()),
            duplicate=("validation_status_clean", lambda s: (s == "Duplicate").sum()),
        )
        .reset_index()
    )
    stations["rejection_rate"] = stations.apply(
        lambda r: r["rejected"] / (r["approved"] + r["rejected"]) * 100
        if (r["approved"] + r["rejected"]) > 0 else 0,
        axis=1,
    )
    stations = stations.sort_values("rejection_rate", ascending=False)
    city_avg = rejection_rate(df["validation_status_clean"])
    result = {
        "stations": stations.to_dict(orient="records"),
        "city_avg": round(city_avg, 1),
    }
    store.station_cache = result
    return result


def get_repeat_offenders() -> dict:
    if store.repeat_offenders_cache:
        return store.repeat_offenders_cache
    df = store.violations
    counts = (
        df.groupby("vehicle_number")
        .agg(
            violation_count=("id", "count"),
            vehicle_type=("vehicle_type_clean", "first"),
            stations=("police_station", lambda s: ", ".join(sorted(s.unique()[:3]))),
            top_location=("location", "first"),
        )
        .reset_index()
        .sort_values("violation_count", ascending=False)
    )
    top50 = counts.head(50)
    repeat_5plus = int((counts["violation_count"] >= 5).sum())

    freq = counts["violation_count"]
    bins = [1, 2, 3, 4, 5, 10, 20, 100]
    labels = ["1", "2", "3", "4", "5-9", "10-19", "20+"]
    freq_df = counts.copy()
    freq_df["bucket"] = pd.cut(freq, bins=bins, labels=labels, right=False, include_lowest=True)
    distribution = freq_df.groupby("bucket", observed=False).size().reset_index(name="vehicles")
    distribution["bucket"] = distribution["bucket"].astype(str)

    result = {
        "top50": top50.to_dict(orient="records"),
        "repeat_5plus": repeat_5plus,
        "distribution": distribution.to_dict(orient="records"),
        "max_violations": int(counts["violation_count"].max()) if not counts.empty else 0,
        "top_vehicle": top50.iloc[0]["vehicle_number"] if not top50.empty else None,
    }
    store.repeat_offenders_cache = result
    return result


def get_feedback_loop(loc_key: str | None = None) -> dict:
    if loc_key is None and store.feedback_cache:
        return store.feedback_cache
    zones = store.zones.sort_values("pcis", ascending=False)
    if not loc_key:
        loc_key = zones.iloc[0]["loc_key"]

    zone = zones[zones["loc_key"] == loc_key].iloc[0]
    df = store.violations[store.violations["loc_key"] == loc_key].copy()
    df["date"] = df["created_datetime"].dt.date

    daily = df.groupby("date").size().reset_index(name="violations")
    daily["date"] = daily["date"].astype(str)
    median_violations = float(daily["violations"].median())
    high_days = daily[daily["violations"] > median_violations * 1.5]
    low_days = daily[daily["violations"] < median_violations * 0.5]

    avg_high = float(high_days["violations"].mean()) if not high_days.empty else median_violations
    avg_low = float(low_days["violations"].mean()) if not low_days.empty else median_violations
    reduction = round((1 - avg_low / avg_high) * 100, 1) if avg_high > 0 else 0

    result = {
        "loc_key": loc_key,
        "location": zone["location"],
        "pcis": round(float(zone["pcis"]), 1),
        "risk_tier": zone["risk_tier"],
        "daily_violations": daily.to_dict(orient="records"),
        "avg_high_enforcement_days": round(avg_high, 1),
        "avg_low_enforcement_days": round(avg_low, 1),
        "estimated_reduction_pct": reduction,
        "hotspot_options": zones.head(20)[["loc_key", "location", "pcis"]].to_dict(orient="records"),
    }
    if loc_key is None:
        store.feedback_cache = result
    return result

# ============================================================================
# Citizen Complaint Engine — Bridge of Trust
# ============================================================================

CITIZEN_STATUS_FLOW = [
    "RECEIVED",
    "UNDER_REVIEW",
    "EVIDENCE_VALID",
    "TICKET_GENERATED",
    "RESOLVED",
]

CITIZEN_REJECT_STATUSES = ["REJECTED"]

ESCLATION_48H = 48
ESCLATION_7D = 168
ESCLATION_14D = 336


def _build_citizen_reports() -> dict:
    df = store.violations.copy()
    df = df.head(5000).copy()

    reports = []
    for idx, (_, row) in enumerate(df.iterrows()):
        hours_since = int((pd.Timestamp.now(tz="UTC") - row["created_datetime"]).total_seconds() / 3600)

        if row["validation_status_clean"] == "Approved":
            state = "RESOLVED"
        elif row["validation_status_clean"] == "Rejected":
            state = "REJECTED"
        elif row["is_anomaly"] == 1:
            state = "UNDER_REVIEW"
        elif hours_since > ESCLATION_14D:
            state = "RESOLVED"
        elif hours_since > ESCLATION_7D:
            state = "RESOLVED"
        elif hours_since > ESCLATION_48H:
            states_pool = ["UNDER_REVIEW", "EVIDENCE_VALID"]
            state = states_pool[idx % len(states_pool)]
        else:
            state = "RECEIVED"

        timeline = []
        created = row["created_datetime"]
        state_order = ["RECEIVED", "UNDER_REVIEW", "EVIDENCE_VALID", "TICKET_GENERATED", "RESOLVED"]
        if state == "REJECTED":
            state_order = ["RECEIVED", "UNDER_REVIEW", "REJECTED"]

        for i, s in enumerate(state_order):
            if s == state:
                timeline.append({
                    "status": s, "timestamp": (created + pd.Timedelta(hours=i * 12)).isoformat(), "active": True,
                })
                break
            timeline.append({
                "status": s, "timestamp": (created + pd.Timedelta(hours=i * 12)).isoformat(), "active": True,
            })

        escalated = hours_since > ESCLATION_48H and state in ["UNDER_REVIEW", "RECEIVED"]
        auto_closed = hours_since > ESCLATION_14D

        reports.append({
            "tracking_id": f"SENTRI-{idx + 1:06d}",
            "status": state,
            "timeline": timeline,
            "location": row["location"],
            "latitude": float(row["latitude"]),
            "longitude": float(row["longitude"]),
            "violation_type": row["violation_type_parsed"],
            "vehicle_number": row["vehicle_number"],
            "reported_at": created.isoformat(),
            "assigned_officer": str(row["created_by_id"]),
            "police_station": row["police_station"],
            "escalated": escalated,
            "auto_closed": auto_closed,
            "hours_pending": hours_since if state not in ["RESOLVED", "REJECTED"] else 0,
        })

    return {
        "total_reports": len(reports),
        "reports": reports,
        "status_counts": {s: sum(1 for r in reports if r["status"] == s) for s in CITIZEN_STATUS_FLOW + CITIZEN_REJECT_STATUSES},
        "escalation_alerts": [r for r in reports if r["escalated"]],
        "my_impact": {
            "resolved_reports": sum(1 for r in reports if r["status"] == "RESOLVED"),
            "total_participation": len(reports),
        },
    }


def get_citizen_reports() -> dict:
    return _build_citizen_reports()


def get_citizen_report(tracking_id: str) -> dict | None:
    reports = _build_citizen_reports()["reports"]
    for r in reports:
        if r["tracking_id"] == tracking_id:
            return r
    return None


# ============================================================================
# Immune System — Dynamic Quality Score (DQS)
# ============================================================================


def get_system_health() -> dict:
    df = store.violations

    officer_stats = (
        df.groupby("created_by_id")
        .agg(
            total_filed=("id", "count"),
            approved=("validation_status_clean", lambda s: (s == "Approved").sum()),
            rejected=("validation_status_clean", lambda s: (s == "Rejected").sum()),
            station=("police_station", "first"),
            avg_anomaly=("anomaly_score", "mean"),
        )
        .reset_index()
    )
    officer_stats["rejection_rate"] = officer_stats.apply(
        lambda r: r["rejected"] / (r["approved"] + r["rejected"]) * 100 if (r["approved"] + r["rejected"]) > 0 else 0,
        axis=1,
    )
    officer_stats["dqs"] = officer_stats.apply(
        lambda r: max(0, min(100, 100 + r["approved"] * 1 - r["rejected"] * 5)), axis=1,
    )
    officer_stats = officer_stats.sort_values("rejection_rate", ascending=False)

    station_stats = (
        df.groupby("police_station")
        .agg(
            total_filed=("id", "count"),
            approved=("validation_status_clean", lambda s: (s == "Approved").sum()),
            rejected=("validation_status_clean", lambda s: (s == "Rejected").sum()),
            unique_officers=("created_by_id", "nunique"),
        )
        .reset_index()
    )
    station_stats["rejection_rate"] = station_stats.apply(
        lambda r: r["rejected"] / (r["approved"] + r["rejected"]) * 100 if (r["approved"] + r["rejected"]) > 0 else 0,
        axis=1,
    )
    station_stats["dqs"] = station_stats.apply(
        lambda r: max(0, min(100, 100 + r["approved"] * 1 - r["rejected"] * 5)), axis=1,
    )

    valid = df[df["validation_status_clean"].isin(["Approved", "Rejected"])]
    city_avg_rejection = float(valid["validation_status_clean"].eq("Rejected").mean() * 100)
    city_std = float(valid["validation_status_clean"].eq("Rejected").std() * 100)

    deviation_alerts = []
    for _, row in station_stats.iterrows():
        if row["rejection_rate"] > city_avg_rejection + 2 * city_std and row["total_filed"] > 50:
            deviation_alerts.append({
                "station": row["police_station"],
                "rejection_rate": round(row["rejection_rate"], 1),
                "city_avg": round(city_avg_rejection, 1),
                "deviation": round(row["rejection_rate"] - city_avg_rejection, 1),
                "severity": "CRITICAL" if row["rejection_rate"] > city_avg_rejection + 3 * city_std else "HIGH",
                "recommendation": "Training/Standards Review recommended",
            })

    rejected_df = df[df["validation_status_clean"] == "Rejected"]
    gps_drift_zones = (
        rejected_df.groupby("loc_key")
        .agg(rejections=("id", "count"), location=("location", "first"))
        .reset_index()
        .sort_values("rejections", ascending=False)
        .head(20)
    )

    return {
        "city_avg_rejection": round(city_avg_rejection, 1),
        "city_std_deviation": round(city_std, 1),
        "officers": officer_stats.head(100).to_dict(orient="records"),
        "stations": station_stats.to_dict(orient="records"),
        "deviation_alerts": deviation_alerts,
        "gps_drift_zones": gps_drift_zones.to_dict(orient="records"),
        "low_quality_threshold": round(city_avg_rejection + city_std, 1),
    }


# ============================================================================
# Tactical Control Simulator — 5 Operational Layers
# ============================================================================


def simulate_tactical_control(lat: float, lon: float, vehicle_type: str) -> dict:
    zones = store.zones.dropna(subset=["latitude", "longitude"]).copy()
    zones["dist"] = ((zones["latitude"].astype(float) - lat) ** 2 + (zones["longitude"].astype(float) - lon) ** 2) ** 0.5
    nearest = zones.loc[zones["dist"].idxmin()] if not zones.empty else None

    nearby = store.violations[
        (abs(store.violations["latitude"] - lat) < 0.01) &
        (abs(store.violations["longitude"] - lon) < 0.01)
    ]
    approval_rate = (nearby["validation_status_clean"] == "Approved").mean() if not nearby.empty else 0.6
    confidence = round(min(1.0, max(0.0, approval_rate)), 2)

    is_heavy = any(k in str(vehicle_type).upper() for k in ["TANKER", "TRUCK", "BUS", "LCV", "LGV"])

    validation_blocked = confidence < 0.6
    steps = []

    steps.append({
        "layer": 0, "name": "Validation Gatekeeper",
        "action": "Check historical approval rate",
        "status": "BLOCKED" if validation_blocked else "PASSED",
        "confidence": confidence,
        "detail": f"Approval rate for this location: {confidence:.0%}", "icon": "🛡️",
    })

    if not validation_blocked:
        is_junction = nearest is not None and nearest.get("pcis", 0) > 30
        steps.append({
            "layer": 1, "name": "Anti-Gridlock Hold",
            "action": "Hold conflicting green phase for 5 seconds",
            "status": "EXECUTED",
            "detail": f"Violation near junction (PCIS: {nearest.get('pcis', 0):.0f})" if is_junction else "No junction near blockage",
            "icon": "🚦",
        })
        steps.append({
            "layer": 2, "name": "Heavy Discharge Extension",
            "action": "Add +7s green for blocked approach (3 cycles)" if is_heavy else "Not triggered (non-heavy vehicle)",
            "status": "EXECUTED" if is_heavy else "SKIPPED",
            "detail": f"{vehicle_type} blocking lane — extended green applied" if is_heavy else f"Vehicle type: {vehicle_type}",
            "icon": "🟢",
        })
        steps.append({
            "layer": 3, "name": "Shockwave Dampening (VMS)",
            "action": "Drop upstream VMS speed to 30 km/h for 5 min",
            "status": "EXECUTED",
            "detail": "Speed advisory sent to nearest VMS board", "icon": "🪧",
        })
        cone_coords = [
            {"lat": round(lat + 0.001 * __import__("math").cos(__import__("math").radians(a * 7)), 6),
             "lon": round(lon + 0.001 * __import__("math").sin(__import__("math").radians(a * 7)), 6)}
            for a in range(8)
        ]
        steps.append({
            "layer": 4, "name": "Zipper-Merge Cone Map",
            "action": "Generate 7-degree cone taper GPS coordinates",
            "status": "DISPLAYED",
            "detail": "QR code ready for beat constable", "icon": "📐",
            "cone_coordinates": cone_coords,
        })

    return {
        "latitude": lat, "longitude": lon, "vehicle_type": vehicle_type,
        "confidence": float(confidence),
        "validation_blocked": bool(validation_blocked),
        "total_layers": len(steps),
        "steps": [
            {
                "layer": s["layer"],
                "name": s["name"],
                "action": s["action"],
                "status": s["status"],
                "confidence": float(s.get("confidence", 0)),
                "detail": s["detail"],
                "icon": s.get("icon", ""),
                **({"cone_coordinates": s["cone_coordinates"]} if "cone_coordinates" in s else {}),
            }
            for s in steps
        ],
        "risk_tier": str(nearest.get("risk_tier", "Unknown")) if nearest is not None else "Unknown",
        "location": str(nearest.get("location", "")) if nearest is not None else "",
        "timestamp": pd.Timestamp.now().isoformat(),
    }


# ============================================================================
# Strategy Lab — What-If Simulation
# ============================================================================


def simulate_strategy(patrol_increase_pct: float = 50.0) -> dict:
    df = store.violations
    zones = store.zones
    high_risk_keys = zones[zones["risk_tier"].isin(["Critical", "High Risk"])]["loc_key"].tolist()
    high_risk_current = len(df[df["loc_key"].isin(high_risk_keys)])

    total_current = len(df)
    elasticity = 0.4
    reduction_pct = patrol_increase_pct * elasticity
    predicted_reduction = int(high_risk_current * reduction_pct / 100)
    predicted_total = total_current - predicted_reduction

    weekly_base = total_current / 4
    projections = []
    for w in range(4):
        r = reduction_pct * (1 - w * 0.15)
        projections.append({
            "week": w + 1,
            "current_trend": int(weekly_base),
            "simulated_trend": int(weekly_base * (1 - r / 100)),
            "reduction_pct": round(r, 1),
        })

    return {
        "patrol_increase_pct": patrol_increase_pct,
        "elasticity_factor": elasticity,
        "total_current_violations": total_current,
        "high_risk_violations": high_risk_current,
        "predicted_reduction": predicted_reduction,
        "predicted_total_after": predicted_total,
        "reduction_pct": round(reduction_pct, 1),
        "weekly_projection": projections,
        "top_zones_impact": zones[zones["risk_tier"].isin(["Critical", "High Risk"])].head(10)[
            ["location", "risk_tier", "total_violations", "pcis"]
        ].to_dict(orient="records"),
    }


# ============================================================================
# Analytics Explorer — Association Rules & Anomaly Explanations
# ============================================================================


def get_analytics_explorer() -> dict:
    df = store.violations

    # Association rules
    ctab = pd.crosstab(df["vehicle_type_clean"], df["violation_type_parsed"], normalize="index")
    rules = []
    for vtype in df["vehicle_type_clean"].value_counts().head(10).index:
        if vtype in ctab.index:
            for vtype2, conf in ctab.loc[vtype].sort_values(ascending=False).head(3).items():
                if conf > 0.05:
                    rules.append({
                        "vehicle_type": vtype,
                        "violation_type": str(vtype2),
                        "confidence": round(float(conf), 3),
                        "support": int((df["vehicle_type_clean"] == vtype).sum()),
                    })
    rules.sort(key=lambda x: x["confidence"], reverse=True)

    # Micro-zone clusters
    clusters = (
        df.groupby("loc_key")
        .agg(
            latitude=("latitude", "first"), longitude=("longitude", "first"),
            location=("location", "first"), violation_count=("id", "count"),
            police_station=("police_station", "first"),
            top_violation=("violation_type_parsed", lambda s: s.mode().iloc[0] if not s.mode().empty else "Unknown"),
            vehicle_diversity=("vehicle_type_clean", "nunique"),
        )
        .reset_index()
        .sort_values("violation_count", ascending=False)
        .head(100)
    )

    # Anomaly explanations
    anomalies = df[df["is_anomaly"] == 1].sort_values("anomaly_score", ascending=False).head(50)
    explanations = []
    for _, row in anomalies.iterrows():
        oid = row["created_by_id"]
        o_total = len(df[df["created_by_id"] == oid])
        o_anomalies = len(df[(df["created_by_id"] == oid) & (df["is_anomaly"] == 1)])
        hourly_rate = o_total / max(1, df[df["created_by_id"] == oid]["hour_int"].nunique())

        reasons = []
        if row["same_second_filing_count"] > 5:
            reasons.append(f"Burst filing: {int(row['same_second_filing_count'])} records in same second")
        if o_anomalies > 10:
            reasons.append(f"Officer {oid} has {o_anomalies} flagged records")
        if hourly_rate > 10:
            reasons.append(f"Unusual filing rate: ~{hourly_rate:.0f}/hr")
        if row["validation_status_clean"] == "Rejected":
            reasons.append("Record was subsequently rejected")
        if not reasons:
            reasons.append("Statistical outlier in feature space")

        explanations.append({
            "anomaly_score": round(float(row["anomaly_score"]), 3),
            "officer_id": oid,
            "police_station": row["police_station"],
            "location": row["location"][:80],
            "violation_type": row["violation_type_parsed"],
            "same_second_count": int(row["same_second_filing_count"]),
            "reasons": reasons,
        })

    station_digit = (
        df.groupby("police_station").agg(total_filed=("id", "count")).reset_index().sort_values("total_filed", ascending=False)
    )
    max_f = station_digit["total_filed"].max() or 1
    station_digit["digitization_rate"] = (station_digit["total_filed"] / max_f * 100).round(1)

    return {
        "clusters": clusters.to_dict(orient="records"),
        "association_rules": rules[:30],
        "anomaly_explanations": explanations,
        "station_digitization": station_digit.to_dict(orient="records"),
    }


SHIFT_WINDOWS = {
    "Morning": (6, 10),
    "Afternoon": (10, 17),
    "Evening": (17, 22),
    "Night": (22, 6),  # wraps midnight, handled specially below
}


def _hours_in_window(start: int, end: int) -> list[int]:
    if start < end:
        return list(range(start, end))
    # Wrapping window (e.g. Night: 22 -> 6 means 22,23,0,1,...,5)
    return list(range(start, 24)) + list(range(0, end))


def get_shift_intelligence(shift: str = "Morning") -> dict:
    """
    Real hour-filtered intelligence for a shift window, replacing the old
    Intelligence Map page's "Time of day filter" -- which changed the page
    title but never actually filtered any data. Every number returned here
    is computed from violations whose hour_int actually falls in the
    selected window.
    """
    if shift not in SHIFT_WINDOWS:
        shift = "Morning"
    start, end = SHIFT_WINDOWS[shift]
    hours = _hours_in_window(start, end)

    df = store.violations
    shift_df = df[df["hour_int"].isin(hours)]

    if shift_df.empty:
        return {
            "shift": shift,
            "hour_range": f"{start:02d}:00–{end:02d}:00",
            "total_violations": 0,
            "share_of_all_violations_pct": 0.0,
            "hourly_profile": [],
            "top_zones": [],
            "top_violation_types": [],
            "top_vehicle_types": [],
            "top_stations": [],
        }

    total_all = len(df)
    total_shift = len(shift_df)

    # Hourly profile across the full 24h, so the selected window can be
    # highlighted in context rather than shown in isolation.
    hourly_counts = df.groupby("hour_int").size().reindex(range(24), fill_value=0)
    hourly_profile = [
        {"hour": h, "count": int(hourly_counts.get(h, 0)), "in_window": h in hours}
        for h in range(24)
    ]

    # Top zones for this shift window specifically -- real ranking by
    # actual violation count in the filtered set, not a fabricated beat
    # boundary based on raw latitude bands.
    zone_counts = (
        shift_df.groupby("loc_key", dropna=False)
        .agg(
            violations=("id", "count"),
            location=("location", "first"),
            police_station=("police_station", "first"),
        )
        .reset_index()
        .sort_values("violations", ascending=False)
        .head(10)
    )
    zone_risk_lookup = store.zones.set_index("loc_key")[["risk_tier", "pcis"]] if not store.zones.empty else pd.DataFrame()
    zone_counts = zone_counts.merge(
        zone_risk_lookup, left_on="loc_key", right_index=True, how="left"
    )
    zone_counts["risk_tier"] = zone_counts["risk_tier"].fillna("Unrated")
    zone_counts["pcis"] = zone_counts["pcis"].fillna(0)

    top_zones = [
        {
            "loc_key": r.loc_key,
            "location": r.location,
            "police_station": r.police_station,
            "violations": int(r.violations),
            "risk_tier": r.risk_tier,
            "pcis": round(float(r.pcis), 1),
        }
        for r in zone_counts.itertuples(index=False)
    ]

    top_violation_types = (
        shift_df["violation_type_parsed"].value_counts().head(6).reset_index()
    )
    top_violation_types.columns = ["violation_type", "count"]

    top_vehicle_types = (
        shift_df["vehicle_type_clean"].value_counts().head(6).reset_index()
    )
    top_vehicle_types.columns = ["vehicle_type", "count"]

    top_stations = (
        shift_df["police_station"].value_counts().head(8).reset_index()
    )
    top_stations.columns = ["police_station", "count"]

    return {
        "shift": shift,
        "hour_range": f"{start:02d}:00–{end:02d}:00",
        "total_violations": total_shift,
        "share_of_all_violations_pct": round(total_shift / total_all * 100, 1) if total_all else 0.0,
        "hourly_profile": hourly_profile,
        "top_zones": top_zones,
        "top_violation_types": top_violation_types.to_dict(orient="records"),
        "top_vehicle_types": top_vehicle_types.to_dict(orient="records"),
        "top_stations": top_stations.to_dict(orient="records"),
    }