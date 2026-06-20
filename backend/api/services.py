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