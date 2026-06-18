"""
Train all ML artifacts: anomaly detection, PCIS zones, Prophet forecasts.
Run: python -m ml.train_all
"""

from __future__ import annotations

import json
import pickle
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

NIGHT_BUCKETS = ["Late Night (12AM-6AM)", "Night (10PM-12AM)"]

ANOMALY_FEATURES = [
    "hour",
    "same_second_filing_count",
    "vehicle_violation_count",
    "location_violation_count",
    "minutes_to_modify",
    "violation_count",
    "offence_code_count",
]

TOP_JUNCTIONS = {
    "safina_plaza": "BTP051 - Safina Plaza Junction",
    "kr_market": "BTP082 - KR Market Junction",
    "elite": "BTP040 - Elite Junction",
    "sagar_theatre": "BTP044 - Sagar Theatre Junction",
    "central_street": "BTP211 - Central Street Junction",
}

PCIS_WEIGHTS = {
    "total_violations": 0.35,
    "night_violations": 0.25,
    "repeat_vehicles": 0.20,
    "commercial_pct": 0.10,
    "peak_concentration": 0.10,
}

RISK_LABELS = ["Low Risk", "Medium Risk", "High Risk", "Critical"]


def _normalize(series: pd.Series) -> pd.Series:
    mx = series.max()
    if mx == 0 or pd.isna(mx):
        return series * 0.0
    return series / mx


def load_data() -> pd.DataFrame:
    print("Loading data…")
    df = pd.read_csv(DATA_PATH, low_memory=False)
    df["created_datetime"] = pd.to_datetime(df["created_datetime"], utc=True)
    df["is_night"] = df["time_bucket"].isin(NIGHT_BUCKETS)
    df["hour_int"] = pd.to_numeric(df["hour"], errors="coerce").fillna(0).astype(int)
    df["is_commercial"] = (df["vehicle_category"] == "Commercial").astype(int)
    df["is_repeat_at_record"] = (df["vehicle_violation_count"] >= 2).astype(int)
    return df


def train_anomaly(df: pd.DataFrame) -> tuple[pd.DataFrame, IsolationForest, StandardScaler]:
    print("Training Isolation Forest…")
    X = df[ANOMALY_FEATURES].copy()
    X["hour"] = pd.to_numeric(X["hour"], errors="coerce")
    X["minutes_to_modify"] = pd.to_numeric(X["minutes_to_modify"], errors="coerce")
    X["same_second_filing_count"] = pd.to_numeric(
        X["same_second_filing_count"], errors="coerce"
    )
    X = X.fillna(
        {
            "hour": X["hour"].median(),
            "minutes_to_modify": X["minutes_to_modify"].median(),
            "same_second_filing_count": 1,
        }
    )

    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    model = IsolationForest(contamination=0.11, random_state=42, n_jobs=-1)
    model.fit(X_scaled)

    scores = -model.score_samples(X_scaled)
    flags = model.predict(X_scaled)

    result = df.copy()
    result["anomaly_score"] = scores
    result["is_anomaly"] = (flags == -1).astype(int)

    joblib.dump(model, ARTIFACTS / "anomaly_model.pkl")
    joblib.dump(scaler, ARTIFACTS / "anomaly_scaler.pkl")

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

    for col in ["total_violations", "night_violations", "repeat_vehicles", "commercial_pct", "peak_concentration"]:
        base[f"n_{col}"] = _normalize(base[col])

    base["pcis"] = sum(
        base[f"n_{col}"] * weight for col, weight in PCIS_WEIGHTS.items()
    ) * 100

    cluster_features = base[
        [f"n_{c}" for c in PCIS_WEIGHTS]
    ].values
    kmeans = KMeans(n_clusters=4, random_state=42, n_init=10)
    base["cluster"] = kmeans.fit_predict(cluster_features)

    cluster_order = (
        base.groupby("cluster")["pcis"]
        .mean()
        .sort_values()
        .index.tolist()
    )
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


def train_forecasts(df: pd.DataFrame) -> dict:
    print("Training Prophet forecasts…")
    FORECAST_DIR.mkdir(parents=True, exist_ok=True)
    forecasts: dict[str, list] = {}

    city_series = _hourly_series(df)
    city_fc = _fit_prophet(city_series)
    city_future = city_fc.tail(24 * 7)
    forecasts["city"] = city_future.to_dict(orient="records")
    with open(FORECAST_DIR / "city.json", "w") as f:
        json.dump(forecasts["city"], f, default=str)

    for key, junction_name in TOP_JUNCTIONS.items():
        sub = df[df["junction_name_clean"] == junction_name]
        if sub.empty:
            continue
        print(f"  Forecasting {key}…")
        series = _hourly_series(sub)
        fc = _fit_prophet(series)
        future = fc.tail(24 * 7)
        records = future.to_dict(orient="records")
        forecasts[key] = records
        with open(FORECAST_DIR / f"{key}.json", "w") as f:
            json.dump(records, f, default=str)

    with open(FORECAST_DIR / "index.json", "w") as f:
        json.dump({"locations": ["city", *TOP_JUNCTIONS.keys()], "junctions": TOP_JUNCTIONS}, f)

    print(f"  Forecasts saved for {len(forecasts)} locations")
    return forecasts


def save_scored_violations(df: pd.DataFrame) -> None:
    cols = [
        "id",
        "latitude",
        "longitude",
        "loc_key",
        "location",
        "created_datetime",
        "hour_int",
        "day_of_week",
        "dow_num",
        "time_bucket",
        "vehicle_number",
        "vehicle_category",
        "vehicle_type_clean",
        "violation_type_parsed",
        "police_station",
        "created_by_id",
        "junction_name_clean",
        "validation_status_clean",
        "same_second_filing_count",
        "is_bulk_filed",
        "is_night",
        "anomaly_score",
        "is_anomaly",
    ]
    available = [c for c in cols if c in df.columns]
    df[available].to_parquet(ARTIFACTS / "violations_scored.parquet", index=False)
    print(f"  Scored violations saved ({len(df):,} rows)")


def main() -> None:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    df = load_data()
    scored, _, _ = train_anomaly(df)
    train_pcis(scored)
    train_forecasts(scored)
    save_scored_violations(scored)

    meta = {
        "total_records": len(scored),
        "anomaly_count": int(scored["is_anomaly"].sum()),
        "anomaly_pct": float(scored["is_anomaly"].mean() * 100),
        "max_same_second": int(scored["same_second_filing_count"].max()),
        "rejected_count": int((scored["validation_status_clean"] == "Rejected").sum()),
    }
    with open(ARTIFACTS / "meta.json", "w") as f:
        json.dump(meta, f, indent=2)

    print("\nAll artifacts saved to artifacts/")


if __name__ == "__main__":
    main()
