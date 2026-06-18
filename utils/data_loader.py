from pathlib import Path

import pandas as pd
import streamlit as st

NIGHT_BUCKETS = ["Late Night (12AM-6AM)", "Night (10PM-12AM)"]
NIGHT_HOURS = set(range(0, 6)) | {22, 23}

DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "parking_violations_clean.csv"


@st.cache_data(show_spinner="Loading 298K violation records…")
def load_violations() -> pd.DataFrame:
    df = pd.read_csv(DATA_PATH, low_memory=False)
    df["created_datetime"] = pd.to_datetime(df["created_datetime"], utc=True)
    df["date"] = pd.to_datetime(df["date"])
    df["is_night"] = df["time_bucket"].isin(NIGHT_BUCKETS)
    df["hour_int"] = pd.to_numeric(df["hour"], errors="coerce").fillna(0).astype(int)
    return df


def rejection_rate(series: pd.Series) -> float:
    approved = (series == "Approved").sum()
    rejected = (series == "Rejected").sum()
    total = approved + rejected
    return (rejected / total * 100) if total else 0.0


@st.cache_data(show_spinner=False)
def get_summary_metrics(_df: pd.DataFrame) -> dict:
    total = len(_df)
    night_count = int(_df["is_night"].sum())
    bulk_count = int(_df["is_bulk_filed"].sum())
    repeat_count = int((_df.groupby("vehicle_number").size() >= 5).sum())
    hotspot_locs = int(_df.loc[_df["is_hotspot"] == 1, "loc_key"].nunique())
    rej = rejection_rate(_df["validation_status_clean"])

    return {
        "total_violations": total,
        "night_violations": night_count,
        "night_pct": night_count / total * 100,
        "bulk_filed": bulk_count,
        "bulk_pct": bulk_count / total * 100,
        "rejection_rate": rej,
        "repeat_offenders": repeat_count,
        "active_hotspots": hotspot_locs,
    }


@st.cache_data(show_spinner=False)
def get_location_aggregates(_df: pd.DataFrame) -> pd.DataFrame:
    agg = (
        _df.groupby("loc_key", as_index=False)
        .agg(
            latitude=("latitude", "first"),
            longitude=("longitude", "first"),
            location=("location", "first"),
            violation_count=("id", "count"),
            is_hotspot=("is_hotspot", "max"),
            top_violation=("violation_type_parsed", "first"),
            top_vehicle=("vehicle_type_clean", "first"),
            police_station=("police_station", "first"),
            approved=("validation_status_clean", lambda s: (s == "Approved").sum()),
            rejected=("validation_status_clean", lambda s: (s == "Rejected").sum()),
            bulk_share=("is_bulk_filed", "mean"),
        )
    )
    agg["rejection_rate"] = agg.apply(
        lambda r: r["rejected"] / (r["approved"] + r["rejected"]) * 100
        if (r["approved"] + r["rejected"]) > 0
        else 0,
        axis=1,
    )

    peak_hours = (
        _df.groupby(["loc_key", "hour_int"])
        .size()
        .reset_index(name="count")
        .sort_values("count", ascending=False)
        .drop_duplicates("loc_key")[["loc_key", "hour_int"]]
        .rename(columns={"hour_int": "peak_hour"})
    )
    return agg.merge(peak_hours, on="loc_key", how="left").fillna({"peak_hour": 0})


@st.cache_data(show_spinner=False)
def get_hotspot_locations(_df: pd.DataFrame) -> pd.DataFrame:
    locs = get_location_aggregates(_df)
    return locs[locs["is_hotspot"] == 1].sort_values("violation_count", ascending=False)


@st.cache_data(show_spinner=False)
def get_junction_aggregates(_df: pd.DataFrame) -> pd.DataFrame:
    junctions = _df[_df["has_junction"] == 1].copy()
    junctions = junctions[junctions["junction_name_clean"] != "No Junction"]
    return (
        junctions.groupby(
            ["junction_name_clean", "latitude", "longitude"], as_index=False
        )
        .agg(
            violation_count=("id", "count"),
            top_violation=("violation_type_parsed", "first"),
            top_vehicle=("vehicle_type_clean", "first"),
            peak_hour=("hour_int", "median"),
        )
        .sort_values("violation_count", ascending=False)
    )


@st.cache_data(show_spinner=False)
def get_hourly_counts(_df: pd.DataFrame) -> pd.DataFrame:
    hourly = _df.groupby("hour_int").size().reset_index(name="violations")
    hourly["period"] = hourly["hour_int"].apply(
        lambda h: "Night" if h in NIGHT_HOURS else "Day"
    )
    return hourly


@st.cache_data(show_spinner=False)
def get_time_bucket_counts(_df: pd.DataFrame) -> pd.DataFrame:
    order = [
        "Late Night (12AM-6AM)",
        "Morning (6AM-10AM)",
        "Midday (10AM-2PM)",
        "Afternoon (2PM-6PM)",
        "Evening (6PM-10PM)",
        "Night (10PM-12AM)",
    ]
    counts = _df["time_bucket"].value_counts().reindex(order).fillna(0).reset_index()
    counts.columns = ["time_bucket", "count"]
    counts["is_night"] = counts["time_bucket"].isin(NIGHT_BUCKETS)
    return counts


@st.cache_data(show_spinner=False)
def get_dow_hour_heatmap(_df: pd.DataFrame) -> pd.DataFrame:
    pivot = (
        _df.groupby(["day_of_week", "hour_int"])
        .size()
        .reset_index(name="violations")
    )
    day_order = [
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
        "Sunday",
    ]
    pivot["day_of_week"] = pd.Categorical(
        pivot["day_of_week"], categories=day_order, ordered=True
    )
    return pivot.sort_values(["day_of_week", "hour_int"])


@st.cache_data(show_spinner=False)
def get_night_day_vehicle_split(_df: pd.DataFrame) -> pd.DataFrame:
    return (
        _df.groupby(["is_night", "vehicle_category"])
        .size()
        .reset_index(name="count")
    )


@st.cache_data(show_spinner=False)
def get_daily_bulk_timeline(_df: pd.DataFrame) -> pd.DataFrame:
    daily = (
        _df.groupby("date")
        .agg(
            total=("id", "count"),
            bulk=("is_bulk_filed", "sum"),
        )
        .reset_index()
    )
    daily["bulk_pct"] = daily["bulk"] / daily["total"] * 100
    return daily.sort_values("date")


@st.cache_data(show_spinner=False)
def get_worst_bulk_events(_df: pd.DataFrame, top_n: int = 20) -> pd.DataFrame:
    bulk = _df[_df["same_second_filing_count"] > 1].copy()
    events = (
        bulk.groupby(
            ["created_datetime", "latitude", "longitude", "location", "created_by_id"],
            as_index=False,
        )
        .agg(
            count=("id", "count"),
            same_second=("same_second_filing_count", "max"),
            police_station=("police_station", "first"),
        )
        .sort_values(["same_second", "count"], ascending=False)
        .head(top_n)
    )
    return events


@st.cache_data(show_spinner=False)
def get_officer_bulk_rates(_df: pd.DataFrame) -> pd.DataFrame:
    officer = (
        _df.groupby("created_by_id")
        .agg(
            total=("id", "count"),
            bulk=("is_bulk_filed", "sum"),
            police_station=("police_station", "first"),
        )
        .reset_index()
    )
    officer = officer[officer["total"] >= 50]
    officer["bulk_pct"] = officer["bulk"] / officer["total"] * 100
    return officer.sort_values("bulk_pct", ascending=False)


@st.cache_data(show_spinner=False)
def get_station_performance(_df: pd.DataFrame) -> pd.DataFrame:
    stations = (
        _df.groupby("police_station")
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
        if (r["approved"] + r["rejected"]) > 0
        else 0,
        axis=1,
    )
    return stations.sort_values("rejection_rate", ascending=False)


@st.cache_data(show_spinner=False)
def get_repeat_offenders(_df: pd.DataFrame, min_violations: int = 2) -> pd.DataFrame:
    counts = _df.groupby("vehicle_number").agg(
        violation_count=("id", "count"),
        vehicle_type=("vehicle_type_clean", "first"),
        stations=("police_station", lambda s: ", ".join(sorted(s.unique()[:3]))),
        top_location=("location", "first"),
    ).reset_index()
    return counts[counts["violation_count"] >= min_violations].sort_values(
        "violation_count", ascending=False
    )


@st.cache_data(show_spinner=False)
def get_repeat_frequency_distribution(_df: pd.DataFrame) -> pd.DataFrame:
    counts = _df.groupby("vehicle_number").size().reset_index(name="violations")
    bins = [1, 2, 3, 4, 5, 10, 20, 100]
    labels = ["1", "2", "3", "4", "5-9", "10-19", "20+"]
    counts["bucket"] = pd.cut(
        counts["violations"],
        bins=bins,
        labels=labels,
        right=False,
        include_lowest=True,
    )
    return counts.groupby("bucket", observed=False).size().reset_index(name="vehicles")


@st.cache_data(show_spinner=False)
def get_vehicle_history(_df: pd.DataFrame, vehicle_number: str) -> pd.DataFrame:
    mask = _df["vehicle_number"].str.upper() == vehicle_number.strip().upper()
    return _df[mask].sort_values("created_datetime")


@st.cache_data(show_spinner=False)
def get_enforcement_zones(
    _df: pd.DataFrame, hour: int, day_of_week: str
) -> pd.DataFrame:
    subset = _df[(_df["hour_int"] == hour) & (_df["day_of_week"] == day_of_week)]
    if subset.empty:
        return pd.DataFrame()

    zones = (
        subset.groupby(
            ["loc_key", "latitude", "longitude", "location", "police_station"],
            as_index=False,
        )
        .agg(
            violations=("id", "count"),
            rejection_rate=("validation_status_clean", rejection_rate),
            bulk_share=("is_bulk_filed", "mean"),
            top_violation=("violation_type_parsed", "first"),
        )
    )
    return zones
