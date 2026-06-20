import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import folium
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from frontend.utils.api_client import get_anomalies
from frontend.utils.ui import insight, page_header

page_header(
    "🤖 Anomaly Detector",
    "Isolation Forest flags records that don't behave like normal violations — no labels needed.",
)

insight(
    "Features: hour, same-second filing count, vehicle/location violation history, "
    "modification lag, charge count, offence code count. Contamination prior: 11%. "
    "A high score means a record's pattern is statistically unusual — not proof of "
    "misconduct. Use this list as a starting point for review, not a conclusion."
)

severity = st.slider(
    "Severity threshold",
    min_value=0.0,
    max_value=0.95,
    value=0.0,
    step=0.05,
    help="Higher = fewer but more extreme anomalies (top percentile)",
)

anomalies = get_anomalies(min_score=severity, limit=1000)
df = pd.DataFrame(anomalies)

if df.empty:
    st.warning("No anomalies at this severity level.")
    st.stop()

# ============================================================================
# SECTION 1: SCOPE — what this threshold actually covers, before showing
# any individual record. Severity is a percentile cut, so its meaning
# changes with where you set the slider; show that instead of assuming
# it's self-explanatory.
# ============================================================================
col1, col2, col3 = st.columns(3)
col1.metric("Records at/above threshold", len(df))
col2.metric("Distinct officers involved", df["created_by_id"].nunique())
col3.metric("Max same-second burst", int(df["same_second_filing_count"].max()))

st.markdown("---")

# ============================================================================
# SECTION 2: PATTERN SUMMARY — replaces the old single-officer "wow moment"
# callout. An anomaly score is a statistical signal, not a finding; this
# stays at the aggregate level (how concentrated the flags are across
# officers) so the page reads as a review queue, not an accusation.
# ============================================================================
st.subheader("📋 Review Queue Summary")

officer_summary = (
    df.groupby("created_by_id")
    .agg(
        flagged_records=("anomaly_score", "count"),
        max_score=("anomaly_score", "max"),
        avg_score=("anomaly_score", "mean"),
        max_same_second_burst=("same_second_filing_count", "max"),
        stations=("police_station", lambda s: ", ".join(sorted(s.dropna().unique()[:3]))),
    )
    .reset_index()
    .sort_values(["flagged_records", "max_score"], ascending=False)
)

top_share = (
    officer_summary.head(5)["flagged_records"].sum() / len(df) * 100 if len(df) else 0
)
concentrated = top_share >= 50

if concentrated:
    st.caption(
        f"The top 5 officers by flagged-record count account for **{top_share:.0f}%** of all "
        f"flagged records at this threshold — a concentrated pattern worth reviewing as a group, "
        f"rather than {len(df)} isolated incidents."
    )
else:
    st.caption(
        f"Flagged records are spread across **{df['created_by_id'].nunique()} officers** "
        f"with no single concentration (top 5 account for {top_share:.0f}% of flags) — "
        "consistent with scattered, lower-pattern anomalies rather than one source."
    )

display_summary = officer_summary.head(15).copy()
display_summary["max_score"] = display_summary["max_score"].round(3)
display_summary["avg_score"] = display_summary["avg_score"].round(3)
display_summary.columns = [
    "Officer ID", "Flagged Records", "Max Score", "Avg Score",
    "Max Same-Sec Burst", "Stations",
]
st.dataframe(display_summary, use_container_width=True, hide_index=True)

st.markdown("---")

# ============================================================================
# SECTION 3: MAP — same dark Folium map, now with a legend so size/color
# encoding (severity) is actually readable, plus a station view toggle
# since 200 unlabeled circles is hard to scan at city scale.
# ============================================================================
st.subheader("🗺️ Flagged Locations")

map_mode = st.radio(
    "View", ["Individual records", "By police station"], horizontal=True, label_visibility="collapsed"
)

map_df = df.head(200)
m = folium.Map(
    location=[map_df["latitude"].median(), map_df["longitude"].median()],
    zoom_start=11,
    tiles="CartoDB dark_matter",
)

score_max = map_df["anomaly_score"].max() or 1

if map_mode == "Individual records":
    for _, row in map_df.iterrows():
        intensity = row["anomaly_score"] / score_max
        folium.CircleMarker(
            location=[row["latitude"], row["longitude"]],
            radius=4 + intensity * 10,
            color="#ef4444",
            fill=True,
            fill_opacity=0.6 + intensity * 0.3,
            popup=(
                f"Score: {row['anomaly_score']:.3f}<br>"
                f"Officer: {row['created_by_id']}<br>"
                f"Same-second: {int(row['same_second_filing_count'])}<br>"
                f"{row['location'][:80]}"
            ),
        ).add_to(m)
else:
    station_agg = (
        map_df.groupby("police_station")
        .agg(
            latitude=("latitude", "median"),
            longitude=("longitude", "median"),
            count=("anomaly_score", "count"),
            avg_score=("anomaly_score", "mean"),
        )
        .reset_index()
    )
    count_max = station_agg["count"].max() or 1
    for _, row in station_agg.iterrows():
        intensity = row["count"] / count_max
        folium.CircleMarker(
            location=[row["latitude"], row["longitude"]],
            radius=6 + intensity * 18,
            color="#ef4444",
            fill=True,
            fill_opacity=0.5 + intensity * 0.4,
            popup=(
                f"<b>{row['police_station']}</b><br>"
                f"{int(row['count'])} flagged records<br>"
                f"Avg score: {row['avg_score']:.3f}"
            ),
        ).add_to(m)

legend_html = """
<div style="position:fixed; bottom:30px; left:30px; z-index:9999;
            background:rgba(15,15,20,0.85); padding:10px 14px; border-radius:8px;
            border:1px solid rgba(239,68,68,0.4); font-size:0.8rem; color:#e5e7eb;">
  <b style="color:#ef4444;">● Anomaly severity</b><br>
  Larger / brighter circle = higher score
</div>
"""
m.get_root().html.add_child(folium.Element(legend_html))

st_folium(m, width=None, height=500, returned_objects=[])

st.markdown("---")

# ============================================================================
# SECTION 4: FULL RECORD TABLE — individual detail still belongs here;
# investigators need it. It's just no longer the headline.
# ============================================================================
st.subheader("Flagged records")
display = df.copy()
display["created_datetime"] = display["created_datetime"].astype(str)
st.dataframe(
    display[
        ["anomaly_score", "created_datetime", "created_by_id", "same_second_filing_count",
         "police_station", "violation_type_parsed", "location"]
    ].rename(columns={
        "anomaly_score": "Score",
        "created_by_id": "Officer",
        "same_second_filing_count": "Same-sec",
        "violation_type_parsed": "Violation",
    }),
    use_container_width=True,
    hide_index=True,
    height=400,
)