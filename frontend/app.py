import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import os

import streamlit as st

from frontend.utils.api_client import api_available
from frontend.utils.ui import apply_brand

st.set_page_config(
    page_title="SENTRI — Bengaluru Parking Intelligence",
    page_icon="🅿️",
    layout="wide",
    initial_sidebar_state="expanded",
)

apply_brand()

if not api_available():
    st.warning(
        "Connecting to the deployed backend... If the API is still warming up, click Reload once more."
    )
    st.caption(f"Using API base: {os.getenv('SENTRI_API_URL', 'http://127.0.0.1:8000')}")
    if st.button("Reload dashboard", use_container_width=True):
        st.rerun()
    st.stop()

pages = [
    st.Page("pages/00_daily_briefing.py", title="Daily Briefing", icon="📋", default=True),
    st.Page("pages/01_patrol_map.py", title="Patrol Map", icon="🗺️"),
    st.Page("pages/11_citizen_portal.py", title="Citizen Portal", icon="🕊️"),
    st.Page("pages/12_system_health.py", title="System Health", icon="🛡️"),
    st.Page("pages/13_control_simulator.py", title="Control Simulator", icon="🎮"),
    st.Page("pages/14_strategy_lab.py", title="Strategy Lab", icon="🧪"),
    st.Page("pages/15_analytics_explorer.py", title="Analytics Explorer", icon="🔬"),
    st.Page("pages/02_violation_forecast.py", title="Violation Forecast", icon="🔮"),
    st.Page("pages/03_anomaly_detector.py", title="Anomaly Detector", icon="🤖"),
    st.Page("pages/04_repeat_offenders.py", title="Repeat Offenders", icon="🔁"),
    st.Page("pages/05_station_audit.py", title="Station Audit", icon="📊"),
    st.Page("pages/07_situation_room.py", title="Situation Room", icon="🧠"),
    st.Page("pages/08_shift_intelligence.py", title="Shift Intelligence", icon="🗺️"),
    st.Page("pages/09_commercial_impact.py", title="Commercial Impact", icon="💼"),
    st.Page("pages/10_offender_fingerprint.py", title="Offender Fingerprint", icon="🧭"),
    st.Page("pages/06_about.py", title="About / Integration Guide", icon="ℹ️"),
]

pg = st.navigation(pages)
pg.run()


