import streamlit as st

from utils.ui import apply_brand

st.set_page_config(
    page_title="ParkIQ — Bengaluru Parking Intelligence",
    page_icon="🅿️",
    layout="wide",
    initial_sidebar_state="expanded",
)

apply_brand()

pages = [
    st.Page("pages/00_daily_briefing.py", title="Daily Briefing", icon="📋", default=True),
    st.Page("pages/01_patrol_map.py", title="Patrol Map", icon="🗺️"),
    st.Page("pages/02_violation_forecast.py", title="Violation Forecast", icon="🔮"),
    st.Page("pages/03_anomaly_detector.py", title="Anomaly Detector", icon="🤖"),
    st.Page("pages/04_repeat_offenders.py", title="Repeat Offenders", icon="🔁"),
    st.Page("pages/05_station_audit.py", title="Station Audit", icon="📊"),
    st.Page("pages/06_about.py", title="About / Integration Guide", icon="ℹ️"),
]

pg = st.navigation(pages)
pg.run()
