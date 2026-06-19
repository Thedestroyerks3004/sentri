import folium
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from frontend.utils.api_client import get_anomalies
from frontend.utils.ui import insight, page_header, wow_moment

page_header(
    "🤖 Anomaly Detector",
    "Isolation Forest flags records that don't behave like normal violations — no labels needed.",
)

insight(
    "Features: hour, same-second filing count, vehicle/location violation history, "
    "modification lag, charge count, offence code count. Contamination prior: 11%."
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

col1, col2, col3 = st.columns(3)
col1.metric("Anomalies shown", len(df))
col2.metric("Max anomaly score", f"{df['anomaly_score'].max():.3f}")
col3.metric("Max same-second burst", int(df["same_second_filing_count"].max()))

top = df.iloc[0]
wow_moment(
    f"Our AI flagged this: officer <b>{top['created_by_id']}</b> — "
    f"<b>{int(top['same_second_filing_count'])}</b> filings in one second. "
    f"Score: <b>{top['anomaly_score']:.3f}</b>"
)

map_df = df.head(200)
m = folium.Map(
    location=[map_df["latitude"].median(), map_df["longitude"].median()],
    zoom_start=11,
    tiles="CartoDB dark_matter",
)

score_max = map_df["anomaly_score"].max() or 1
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

st_folium(m, width=None, height=500, returned_objects=[])

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
