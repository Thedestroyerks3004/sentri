"""
Train all ML artifacts: anomaly detection, PCIS zones, Prophet forecasts.
Run: python -m ml.train_all

Schema-driven design notes
---------------------------
This version replaces several previously-hardcoded assumptions with runtime
introspection of the dataframe, so the pipeline adapts to whichever columns
are actually present in a given export rather than assuming one fixed shape:

- Offence categorization no longer guesses from free-text (`violation_type`)
  via regex. It reads the dataset's own one-hot `vtype_*` flags directly
  (e.g. `vtype_no_parking`, `vtype_jumping_traffic_signal`). Any `vtype_*`
  column not in `VTYPE_CATEGORY_MAP` falls back to "other" and is logged,
  so new flags added to a future export degrade gracefully instead of
  silently mis-categorizing.
- Anomaly-detection features auto-include any `*_enc` (label-encoded
  categorical) column found in the data, on top of a base numeric feature
  list, and skip base features that don't exist instead of KeyError-ing.
- Top junctions are discovered from the data (`junction_name_clean` +
  `has_junction`) by volume, instead of a hardcoded list of five names.
- "Night" is derived from the `hour` column with a configurable threshold,
  falling back to substring-matching `time_bucket` only if no hour column
  exists — instead of relying on two exact label strings.
- Commercial-vehicle detection still relies on a keyword list (there's no
  boolean "is commercial" column in the source data), but it now logs which
  actual `vehicle_category` values matched, so you can see/audit it instead
  of trusting a silent regex.

What's intentionally still a hardcoded constant: fine amounts (a policy/legal
fact, not something inferable from the data), PCIS scoring weights, risk-tier
count, anomaly contamination rate, and offender-classification thresholds.
These are modeling/business choices, not schema assumptions, so they stay as
named constants you can tune at the top of the file.
"""

from __future__ import annotations

import json
import re
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from prophet import Prophet
from sklearn.cluster import KMeans
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = ROOT / "data" / "parking_violations_clean.csv"
ARTIFACTS = ROOT / "artifacts"
FORECAST_DIR = ARTIFACTS / "forecasts"
FINE_CONFIG_PATH = ROOT / "config" / "fine_table.json"  # optional override, see _load_fine_table

# ---------------------------------------------------------------------------
# Schema-driven offence categorization
# ---------------------------------------------------------------------------

VTYPE_PREFIX = "vtype_"

# Maps the suffix of a `vtype_*` one-hot column (these are already decoded,
# human-readable flags in the source data) to a coarser category bucket used
# for fines and offender clustering. Only columns that actually exist on the
# dataframe are ever consulted — add a future `vtype_*` column here when you
# see it logged as unmapped; until then it's bucketed as "other".
VTYPE_CATEGORY_MAP = {
    "jumping_traffic_signal": "signal_violation",
    "no_parking": "no_parking",
    "wrong_parking": "no_parking",
    "double_parking": "no_parking",
    "parking_on_footpath": "no_parking",
    "parking_in_a_main_road": "no_parking",
    "parking_near_bustop_school_hospital_etc": "no_parking",
    "parking_near_road_crossing": "no_parking",
    "parking_near_traffic_light_or_zebra_cross": "no_parking",
    "parking_opposite_to_another_parked_vehicle": "no_parking",
    "parking_other_than_bus_stop": "no_parking",
    "stoping_on_white_stop_line": "no_parking",
    "2w_3w_-_using_mobile_phone": "mobile_phone_use",
    "other_-_using_mobile_phone": "mobile_phone_use",
    "violating_lane_disipline": "lane_discipline",
    "against_one_way_no_entry": "lane_discipline",
    "u_turn_prohibited": "lane_discipline",
    "obstructing_driver": "obstruction",
    "h_t_v_prohibited": "obstruction",
    "carrying_lenghty_material": "load_safety",
    "defective_number_plate": "documentation",
    "without_side_mirror": "documentation",
    "using_black_film_other_materials": "documentation",
    "demanding_excess_fare": "commercial_malpractice",
    "refuse_to_go_for_hire": "commercial_malpractice",
    "fail_to_use_safety_belts": "safety_gear",
    "rider_not_wearing_helmet": "safety_gear",
}

# Default fine per category bucket (INR). This is a legal/policy fact, not
# something derivable from the dataset — but it can be overridden without a
# code change by dropping a {"category": amount} JSON at FINE_CONFIG_PATH.
DEFAULT_CATEGORY_FINES = {
    "no_parking": 1000,
    "signal_violation": 5000,
    "mobile_phone_use": 3000,
    "lane_discipline": 1000,
    "obstruction": 1000,
    "load_safety": 1000,
    "documentation": 500,
    "commercial_malpractice": 2000,
    "safety_gear": 1000,
    "other": 1000,
}

RISK_LABELS = ["Low Risk", "Medium Risk", "High Risk", "Critical"]

PCIS_WEIGHTS = {
    "total_violations": 0.35,
    "night_violations": 0.25,
    "repeat_vehicles": 0.20,
    "commercial_pct": 0.10,
    "peak_concentration": 0.10,
}

# Business-rule constants (not schema assumptions — tune freely).
NIGHT_START_HOUR = 22
NIGHT_END_HOUR = 6
BUSINESS_HOURS_RANGE = (9, 18)
PEAK_RUSH_RANGES = [(7, 10), (17, 20)]
HABITUAL_MAX_DISTINCT_ZONES = 2
OPPORTUNISTIC_MIN_DISTINCT_ZONES = 4
ORGANIZED_CLUSTER_MIN_VEHICLES = 3
TOP_N_JUNCTIONS = 5
ISOLATION_FOREST_CONTAMINATION = 0.11
KMEANS_N_CLUSTERS = 4

AVG_BLOCKAGE_MINUTES = 8
VEHICLES_DELAYED_PER_HOUR = 4
PER_MINUTE_COMMERCIAL_VALUE_INR = 4
HIGH_RISK_ZONE_MULTIPLIER = 1.75

COMMERCIAL_KEYWORDS = r"commercial|goods|delivery|auto|bus|cab|taxi|lcv|school|truck|lorry|tempo|van"

# Base numeric features for the anomaly model. Anything missing from the
# data is skipped (with a log line) rather than raising a KeyError, and any
# `*_enc` column present in the data is auto-appended on top of this list.
BASE_ANOMALY_FEATURES = [
    "hour",
    "same_second_filing_count",
    "vehicle_violation_count",
    "location_violation_count",
    "minutes_to_modify",
    "violation_count",
    "offence_code_count",
]


def _load_fine_table() -> dict:
    fines = dict(DEFAULT_CATEGORY_FINES)
    if FINE_CONFIG_PATH.exists():
        try:
            override = json.loads(FINE_CONFIG_PATH.read_text())
            fines.update(override)
            print(f"  [fine table] loaded overrides from {FINE_CONFIG_PATH}")
        except (json.JSONDecodeError, OSError) as exc:
            print(f"  [fine table] ignoring unreadable config at {FINE_CONFIG_PATH}: {exc}")
    return fines


def _discover_vtype_columns(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns if c.startswith(VTYPE_PREFIX)]


def add_offence_category_and_fine(df: pd.DataFrame, fine_table: dict | None = None) -> pd.DataFrame:
    """Derive `offence_category` (primary, for clustering) and `fine_amount`
    (sum across every true flag, for revenue estimates) directly from the
    dataset's own `vtype_*` one-hot columns — no text parsing involved.
    """
    fine_table = fine_table or _load_fine_table()
    vtype_cols = _discover_vtype_columns(df)

    if not vtype_cols:
        print("  [offence mapping] no vtype_* columns found in data; everything falls back to 'other'")
        df["offence_category"] = "other"
        df["fine_amount"] = fine_table["other"]
        return df

    col_to_category = {}
    unmapped = []
    for c in vtype_cols:
        suffix = c[len(VTYPE_PREFIX):]
        category = VTYPE_CATEGORY_MAP.get(suffix)
        if category is None:
            category = "other"
            unmapped.append(c)
        col_to_category[c] = category
    if unmapped:
        print(f"  [offence mapping] {len(unmapped)} vtype_* columns have no category rule, defaulting to 'other': {unmapped}")

    flags = df[vtype_cols].fillna(0).astype(int).to_numpy()
    fine_per_col = np.array([fine_table.get(col_to_category[c], fine_table["other"]) for c in vtype_cols])

    # Fine = sum of every true flag's fine. Rows can have multiple offence
    # flags set at once, so summing (rather than picking one) reflects the
    # actual filing instead of guessing a single dominant offence.
    df["fine_amount"] = flags @ fine_per_col

    # Primary/dominant category = first true flag in column order. Used only
    # for clustering labels where a single category per row is needed.
    any_flag = flags.any(axis=1)
    first_true_idx = flags.argmax(axis=1)
    category_lookup = np.array([col_to_category[c] for c in vtype_cols])
    df["offence_category"] = np.where(any_flag, category_lookup[first_true_idx], "other")
    return df


# ---------------------------------------------------------------------------
# Schema-driven derived columns
# ---------------------------------------------------------------------------

def add_is_night(df: pd.DataFrame) -> pd.DataFrame:
    if "hour_int" in df.columns or "hour" in df.columns:
        hour = pd.to_numeric(df.get("hour_int", df.get("hour")), errors="coerce")
        df["is_night"] = (hour >= NIGHT_START_HOUR) | (hour < NIGHT_END_HOUR)
    elif "time_bucket" in df.columns:
        print("  [is_night] no hour column found, falling back to matching 'night' in time_bucket labels")
        df["is_night"] = df["time_bucket"].fillna("").astype(str).str.contains("night", case=False)
    else:
        print("  [is_night] no hour or time_bucket column found; defaulting is_night to False")
        df["is_night"] = False
    return df


def add_is_commercial(df: pd.DataFrame) -> pd.DataFrame:
    if "vehicle_category" not in df.columns:
        print("  [is_commercial] no vehicle_category column found; defaulting is_commercial to 0")
        df["is_commercial"] = 0
        return df
    cats = df["vehicle_category"].fillna("").astype(str)
    uniques = sorted(c for c in cats.unique() if c)
    matched = [c for c in uniques if re.search(COMMERCIAL_KEYWORDS, c.lower())]
    print(f"  [is_commercial] {len(matched)}/{len(uniques)} vehicle_category values matched as commercial: {matched}")
    df["is_commercial"] = cats.str.lower().str.contains(COMMERCIAL_KEYWORDS, regex=True).astype(int)
    return df


def add_is_repeat(df: pd.DataFrame) -> pd.DataFrame:
    if "vehicle_violation_count" in df.columns:
        df["is_repeat_at_record"] = (df["vehicle_violation_count"] >= 2).astype(int)
    else:
        print("  [is_repeat] no vehicle_violation_count column found; defaulting is_repeat_at_record to 0")
        df["is_repeat_at_record"] = 0
    return df


def discover_top_junctions(df: pd.DataFrame, n: int = TOP_N_JUNCTIONS) -> dict[str, str]:
    """Pick the top-N junctions by violation volume instead of a hardcoded list."""
    if "junction_name_clean" not in df.columns:
        print("  [junctions] no junction_name_clean column found; skipping junction-level forecasts")
        return {}
    names = df["junction_name_clean"].fillna("").astype(str)
    if "has_junction" in df.columns:
        names = names[df["has_junction"].astype(bool)]
    counts = names[names != ""].value_counts().head(n)
    junctions = {}
    for name in counts.index:
        key = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
        junctions[key] = name
    print(f"  [junctions] discovered top {len(junctions)} by volume: {list(junctions.values())}")
    return junctions


def resolve_anomaly_features(df: pd.DataFrame) -> list[str]:
    features = [c for c in BASE_ANOMALY_FEATURES if c in df.columns]
    missing = [c for c in BASE_ANOMALY_FEATURES if c not in df.columns]
    if missing:
        print(f"  [anomaly features] missing from data, skipping: {missing}")
    enc_cols = [c for c in df.columns if c.endswith("_enc") and c not in features]
    if enc_cols:
        print(f"  [anomaly features] auto-including label-encoded columns: {enc_cols}")
        features += enc_cols
    if not features:
        raise ValueError("No usable features found for anomaly detection — check column names.")
    return features


def _normalize(series: pd.Series) -> pd.Series:
    mx = series.max()
    if mx == 0 or pd.isna(mx):
        return series * 0.0
    return series / mx


def _dominant_by_group(df: pd.DataFrame, group_col: str, value_col: str, out_name: str) -> pd.DataFrame:
    """Most frequent `value_col` per `group_col`, ties broken by the
    alphabetically-smallest value, via groupby+idxmax (no full sort needed
    because groupby([group_col, value_col]).size() is already sorted by key).
    """
    counts = (
        df.groupby([group_col, value_col], dropna=False)
        .size()
        .rename("_count")
        .reset_index()
    )
    idx = counts.groupby(group_col)["_count"].idxmax()
    return (
        counts.loc[idx, [group_col, value_col]]
        .rename(columns={value_col: out_name})
        .reset_index(drop=True)
    )


def load_data() -> pd.DataFrame:
    print("Loading data…")
    df = pd.read_csv(DATA_PATH, low_memory=False)
    df["created_datetime"] = pd.to_datetime(df["created_datetime"], utc=True)
    if "hour" in df.columns:
        df["hour_int"] = pd.to_numeric(df["hour"], errors="coerce").fillna(0).astype(int)
    df = add_is_night(df)
    df = add_is_commercial(df)
    df = add_is_repeat(df)
    df = add_offence_category_and_fine(df)
    return df


def compute_commercial_impact(df: pd.DataFrame) -> dict:
    df = df.copy()
    zone_path = ARTIFACTS / "zone_risk.parquet"
    zone_df = pd.read_parquet(zone_path) if zone_path.exists() else pd.DataFrame()

    if not zone_df.empty and {"location", "risk_tier"}.issubset(zone_df.columns):
        zone_lookup = zone_df[["location", "risk_tier"]].drop_duplicates()
        df = df.merge(zone_lookup, on="location", how="left")
        df["zone_multiplier"] = df["risk_tier"].astype(str).isin(["High Risk", "Critical"]).map(
            {False: 1.0, True: HIGH_RISK_ZONE_MULTIPLIER}
        )
    else:
        df["zone_multiplier"] = 1.0

    commercial_mask = df["is_commercial"].astype(bool)
    df["commercial_mask"] = commercial_mask.astype(int)
    df["delay_cost"] = (
        AVG_BLOCKAGE_MINUTES
        * VEHICLES_DELAYED_PER_HOUR
        * PER_MINUTE_COMMERCIAL_VALUE_INR
        * df["zone_multiplier"]
    )

    fine_by_zone = (
        df.groupby("location", dropna=False)["fine_amount"]
        .sum()
        .reset_index(name="fine_revenue")
    )
    delay_by_zone = (
        df[df["commercial_mask"] == 1]
        .groupby("location", dropna=False)["delay_cost"]
        .sum()
        .reset_index(name="delay_cost")
    )
    by_zone = (
        fine_by_zone.merge(delay_by_zone, on="location", how="outer")
        .fillna({"fine_revenue": 0.0, "delay_cost": 0.0})
        .sort_values(["fine_revenue", "delay_cost"], ascending=False)
        .rename(columns={"location": "zone"})
        .to_dict(orient="records")
    )

    weekly_fine_revenue = float(df["fine_amount"].sum())
    weekly_delay_cost = float(df.loc[df["commercial_mask"] == 1, "delay_cost"].sum())
    top_cost_zone = max(
        by_zone,
        key=lambda x: x["fine_revenue"] + x["delay_cost"],
        default={"zone": "N/A"},
    )["zone"]

    unmapped_count = int((df["offence_category"] == "other").sum())

    methodology_note = (
        "Fine revenue is the sum of fines for every vtype_* flag set on a row (a row can carry more than "
        "one offence flag), using a configurable per-category fine table; the zone multiplier is "
        f"{HIGH_RISK_ZONE_MULTIPLIER}x for High Risk/Critical zones and 1.0x otherwise; commercial delay cost is "
        f"estimated as {AVG_BLOCKAGE_MINUTES} minutes × {VEHICLES_DELAYED_PER_HOUR} delayed vehicles/hour × "
        f"{PER_MINUTE_COMMERCIAL_VALUE_INR} INR/minute per zone, and the current dataset snapshot is treated as "
        "one weekly window."
    )

    return {
        "weekly_fine_revenue": weekly_fine_revenue,
        "weekly_delay_cost": weekly_delay_cost,
        "commercial_vehicles_flagged": int(df["commercial_mask"].sum()),
        "by_zone": by_zone,
        "top_cost_zone": top_cost_zone,
        "uncategorized_offence_rows": unmapped_count,
        "methodology_note": methodology_note,
    }


def compute_offender_fingerprint(df: pd.DataFrame) -> dict:
    df = df.copy()
    df["created_datetime"] = pd.to_datetime(df["created_datetime"], utc=True)
    if "hour_int" not in df.columns:
        df["hour_int"] = pd.to_numeric(df.get("hour"), errors="coerce").fillna(0).astype(int)

    hour = df["hour_int"].to_numpy()
    bh_start, bh_end = BUSINESS_HOURS_RANGE
    time_window = np.full(len(df), "night_other", dtype=object)
    time_window[(hour >= bh_start) & (hour < bh_end)] = "business_hours"
    peak_mask = np.zeros(len(df), dtype=bool)
    for start, end in PEAK_RUSH_RANGES:
        peak_mask |= (hour >= start) & (hour < end)
    still_default = time_window == "night_other"
    time_window[still_default & peak_mask] = "peak_rush"
    df["time_window"] = time_window

    vehicle_stats = (
        df.groupby("vehicle_number", dropna=False)
        .agg(
            total_violations=("id", "count"),
            distinct_zones=("location", "nunique"),
        )
        .reset_index()
    )

    dominant_zone = _dominant_by_group(df, "vehicle_number", "location", "dominant_zone")
    dominant_time = _dominant_by_group(df, "vehicle_number", "time_window", "dominant_time_window")
    dominant_offence = _dominant_by_group(df, "vehicle_number", "offence_category", "dominant_offence_code")

    vehicle_stats = (
        vehicle_stats.merge(dominant_zone, on="vehicle_number", how="left")
        .merge(dominant_time, on="vehicle_number", how="left")
        .merge(dominant_offence, on="vehicle_number", how="left")
    )
    vehicle_stats["dominant_zone"] = vehicle_stats["dominant_zone"].fillna("Unknown")
    vehicle_stats["dominant_time_window"] = vehicle_stats["dominant_time_window"].fillna("night_other")
    vehicle_stats["dominant_offence_code"] = vehicle_stats["dominant_offence_code"].fillna("other")

    habitual_mask = (vehicle_stats["distinct_zones"] <= HABITUAL_MAX_DISTINCT_ZONES) & (
        vehicle_stats["dominant_time_window"] == "business_hours"
    )
    opportunistic_mask = (~habitual_mask) & (vehicle_stats["distinct_zones"] >= OPPORTUNISTIC_MIN_DISTINCT_ZONES)

    habitual_df = vehicle_stats.loc[habitual_mask, ["vehicle_number", "total_violations", "dominant_zone"]]
    habitual = [
        {"vehicle_number": r.vehicle_number, "violations": int(r.total_violations), "dominant_zone": r.dominant_zone}
        for r in habitual_df.itertuples(index=False)
    ]

    opportunistic_df = vehicle_stats.loc[opportunistic_mask, ["vehicle_number", "total_violations", "dominant_zone"]]
    opportunistic = [
        {"vehicle_number": r.vehicle_number, "violations": int(r.total_violations), "dominant_zone": r.dominant_zone}
        for r in opportunistic_df.itertuples(index=False)
    ]

    cluster_groups = (
        vehicle_stats.groupby(
            ["dominant_zone", "dominant_time_window", "dominant_offence_code"],
            dropna=False,
        )
        .agg(
            vehicle_numbers=("vehicle_number", lambda s: sorted(set(s.dropna().astype(str)))),
            vehicle_count=("vehicle_number", "nunique"),
        )
        .reset_index()
    )
    organized_clusters = [
        {
            "zone": row["dominant_zone"],
            "time_window": row["dominant_time_window"],
            "offence": row["dominant_offence_code"],
            "vehicle_numbers": row["vehicle_numbers"],
            "vehicle_count": int(row["vehicle_count"]),
        }
        for _, row in cluster_groups.iterrows()
        if row["vehicle_count"] >= ORGANIZED_CLUSTER_MIN_VEHICLES
    ]

    return {
        "habitual": {"count": len(habitual), "vehicles": habitual},
        "opportunistic": {"count": len(opportunistic), "vehicles": opportunistic},
        "organized_clusters": organized_clusters,
        "uncategorized_count": int(len(vehicle_stats) - len(habitual) - len(opportunistic)),
    }


def train_anomaly(df: pd.DataFrame) -> tuple[pd.DataFrame, IsolationForest, StandardScaler]:
    print("Training Isolation Forest…")
    features = resolve_anomaly_features(df)
    X = df[features].apply(pd.to_numeric, errors="coerce")
    X = X.fillna(X.median(numeric_only=True))

    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    model = IsolationForest(contamination=ISOLATION_FOREST_CONTAMINATION, random_state=42, n_jobs=-1)
    model.fit(X_scaled)

    scores = -model.score_samples(X_scaled)
    flags = model.predict(X_scaled)

    result = df.copy()
    result["anomaly_score"] = scores
    result["is_anomaly"] = (flags == -1).astype(int)

    joblib.dump(model, ARTIFACTS / "anomaly_model.pkl")
    joblib.dump(scaler, ARTIFACTS / "anomaly_scaler.pkl")
    joblib.dump(features, ARTIFACTS / "anomaly_features.pkl")

    print(f"  Features used: {features}")
    print(f"  Anomalies flagged: {result['is_anomaly'].sum():,} ({result['is_anomaly'].mean()*100:.1f}%)")
    return result, model, scaler


def train_pcis(df: pd.DataFrame) -> pd.DataFrame:
    print("Computing PCIS zone scores…")

    base = (
        df.groupby("loc_key", as_index=False)
        .agg(
            latitude=("latitude", "first"),
            longitude=("longitude", "first"),
            location=("location", "first"),
            police_station=("police_station", "first"),
            total_violations=("id", "count"),
            night_violations=("is_night", "sum"),
            repeat_vehicles=("is_repeat_at_record", "sum"),
            commercial_pct=("is_commercial", "mean"),
        )
    )

    hour_peak = (
        df.groupby(["loc_key", "hour_int"])
        .size()
        .reset_index(name="hour_count")
    )
    peak_by_loc = (
        hour_peak.sort_values("hour_count", ascending=False)
        .drop_duplicates("loc_key")
        .set_index("loc_key")["hour_count"]
    )
    base["peak_hour_count"] = base["loc_key"].map(peak_by_loc).fillna(0)
    base["peak_concentration"] = base["peak_hour_count"] / base["total_violations"].clip(lower=1)

    for col in PCIS_WEIGHTS:
        base[f"n_{col}"] = _normalize(base[col])

    base["pcis"] = sum(base[f"n_{col}"] * weight for col, weight in PCIS_WEIGHTS.items()) * 100

    cluster_features = base[[f"n_{c}" for c in PCIS_WEIGHTS]].values
    kmeans = KMeans(n_clusters=KMEANS_N_CLUSTERS, random_state=42, n_init=10)
    base["cluster"] = kmeans.fit_predict(cluster_features)

    cluster_order = base.groupby("cluster")["pcis"].mean().sort_values().index.tolist()
    label_map = {cluster: RISK_LABELS[i] for i, cluster in enumerate(cluster_order)}
    base["risk_tier"] = base["cluster"].map(label_map)

    joblib.dump(kmeans, ARTIFACTS / "pcis_kmeans.pkl")
    base.to_parquet(ARTIFACTS / "zone_risk.parquet", index=False)
    print(f"  Zones scored: {len(base):,}")
    print(base["risk_tier"].value_counts().to_string())
    return base


def _hourly_series(df: pd.DataFrame) -> pd.DataFrame:
    ts = pd.to_datetime(df["created_datetime"]).dt.tz_localize(None)
    hourly = ts.dt.floor("h").value_counts().sort_index().reset_index()
    hourly.columns = ["ds", "y"]
    return hourly


def _fit_prophet(series: pd.DataFrame) -> pd.DataFrame:
    model = Prophet(
        daily_seasonality=True,
        weekly_seasonality=True,
        yearly_seasonality=False,
        changepoint_prior_scale=0.05,
    )
    model.fit(series)
    future = model.make_future_dataframe(periods=24 * 7, freq="h")
    forecast = model.predict(future)
    return forecast[["ds", "yhat", "yhat_lower", "yhat_upper"]]


def _fit_one_location(key: str, series: pd.DataFrame) -> tuple[str, list]:
    fc = _fit_prophet(series)
    records = fc.tail(24 * 7).to_dict(orient="records")
    return key, records


def train_forecasts(df: pd.DataFrame, junctions: dict[str, str]) -> dict:
    """Independent Prophet fits (city + each discovered junction) run in
    separate processes since they don't depend on each other."""
    print("Training Prophet forecasts…")
    FORECAST_DIR.mkdir(parents=True, exist_ok=True)

    series_by_key = {"city": _hourly_series(df)}
    for key, junction_name in junctions.items():
        sub = df[df["junction_name_clean"] == junction_name]
        if sub.empty:
            continue
        series_by_key[key] = _hourly_series(sub)

    forecasts: dict[str, list] = {}
    with ProcessPoolExecutor(max_workers=min(len(series_by_key), 6)) as executor:
        futures = {
            executor.submit(_fit_one_location, key, series): key
            for key, series in series_by_key.items()
        }
        for future in futures:
            key, records = future.result()
            forecasts[key] = records
            with open(FORECAST_DIR / f"{key}.json", "w") as f:
                json.dump(records, f, default=str)
            print(f"  Forecast done: {key}")

    with open(FORECAST_DIR / "index.json", "w") as f:
        json.dump({"locations": list(forecasts.keys()), "junctions": junctions}, f)

    print(f"  Forecasts saved for {len(forecasts)} locations")
    return forecasts


def save_scored_violations(df: pd.DataFrame) -> None:
    cols = [
        "id", "latitude", "longitude", "loc_key", "location", "created_datetime",
        "hour_int", "day_of_week", "dow_num", "time_bucket", "vehicle_number",
        "vehicle_category", "vehicle_type_clean", "violation_type_parsed",
        "police_station", "created_by_id", "junction_name_clean",
        "validation_status_clean", "same_second_filing_count", "is_bulk_filed",
        "is_night", "offence_category", "fine_amount", "anomaly_score", "is_anomaly",
    ]
    available = [c for c in cols if c in df.columns]
    df[available].to_parquet(ARTIFACTS / "violations_scored.parquet", index=False)
    print(f"  Scored violations saved ({len(df):,} rows)")


def main() -> None:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    df = load_data()
    scored, _, _ = train_anomaly(df)
    train_pcis(scored)
    junctions = discover_top_junctions(scored)
    train_forecasts(scored, junctions)
    save_scored_violations(scored)

    commercial_impact = compute_commercial_impact(scored)
    with open(ARTIFACTS / "commercial_impact.json", "w", encoding="utf-8") as f:
        json.dump(commercial_impact, f, indent=2)

    offender_fingerprint = compute_offender_fingerprint(scored)
    with open(ARTIFACTS / "offender_fingerprint.json", "w", encoding="utf-8") as f:
        json.dump(offender_fingerprint, f, indent=2)

    meta = {
        "total_records": len(scored),
        "anomaly_count": int(scored["is_anomaly"].sum()),
        "anomaly_pct": float(scored["is_anomaly"].mean() * 100),
        "max_same_second": int(scored["same_second_filing_count"].max()) if "same_second_filing_count" in scored.columns else None,
        "rejected_count": int((scored["validation_status_clean"] == "Rejected").sum()) if "validation_status_clean" in scored.columns else None,
    }
    with open(ARTIFACTS / "meta.json", "w") as f:
        json.dump(meta, f, indent=2)

    print("\nAll artifacts saved to artifacts/")


if __name__ == "__main__":
    main()