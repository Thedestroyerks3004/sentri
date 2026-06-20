import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

from frontend.utils.ui import apply_brand, format_indian, page_header

API_BASE_DEFAULT = "http://127.0.0.1:8000"

apply_brand()
page_header(
    "🕐 Shift Intelligence",
    "What actually changes by time of day — real violation patterns, not a map.",
)

# ----------------------------------------------------------------------
# This replaces the old "Intelligence Map" page. That page had five map
# layers; three were fabricated (a time-of-day filter that changed the
# title but never filtered any data, hardcoded "patrol beat" boundaries
# based on arbitrary latitude bands with no relation to real station
# jurisdictions, and hardcoded fake traffic-avoidance routes unrelated to
# any zone data), and a fourth ("Patrol Deployment") duplicated the
# existing Patrol Map page. The one genuinely useful, data-real idea --
# "what's different about enforcement at different times of day" -- is
# built out properly here instead, with every number actually filtered
# by hour_int.
# ----------------------------------------------------------------------

SHIFT_WINDOWS = {
    "Morning": "06:00–10:00",
    "Afternoon": "10:00–17:00",
    "Evening": "17:00–22:00",
    "Night": "22:00–06:00",
}


@st.cache_data(ttl=300, show_spinner=False)
def _load_shift(shift: str) -> dict:
    import os

    api_base = os.getenv("SENTRI_API_URL", API_BASE_DEFAULT).rstrip("/")
    resp = requests.get(f"{api_base}/api/shift-intelligence", params={"shift": shift}, timeout=30)
    resp.raise_for_status()
    return resp.json()


shift = st.radio(
    "Shift window",
    options=list(SHIFT_WINDOWS.keys()),
    index=0,
    horizontal=True,
)
st.caption(f"**{shift}** · {SHIFT_WINDOWS[shift]} IST — every number below is filtered to this window.")

try:
    data = _load_shift(shift)
except Exception as exc:
    st.error("Could not load shift intelligence from the API.")
    st.caption(str(exc))
    st.stop()

if data.get("total_violations", 0) == 0:
    st.info(f"No violations recorded for the {shift} window in the current dataset.")
    st.stop()

# ============================================================================
# HEADLINE
# ============================================================================
c1, c2 = st.columns(2)
c1.metric(f"{shift} violations", format_indian(data["total_violations"]))
c2.metric("Share of all violations", f"{data['share_of_all_violations_pct']:.1f}%")

st.markdown("---")

# ============================================================================
# HOURLY PROFILE — real distribution across all 24 hours, with the
# selected shift window highlighted, so "Night" isn't shown in isolation
# but in context of the full day's pattern.
# ============================================================================
st.subheader("📈 24-Hour Violation Profile")

profile = pd.DataFrame(data["hourly_profile"])
colors = ["#3b82f6" if not in_win else "#ef4444" for in_win in profile["in_window"]]

fig = go.Figure(
    go.Bar(
        x=profile["hour"],
        y=profile["count"],
        marker_color=colors,
        hovertemplate="Hour %{x}:00 — %{y:,} violations<extra></extra>",
    )
)
fig.update_layout(
    template="plotly_dark",
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    height=320,
    margin=dict(t=20, r=10, l=10, b=10),
    xaxis=dict(title="Hour of day (IST)", tickmode="linear", dtick=1),
    yaxis_title="Violations",
)
st.plotly_chart(fig, use_container_width=True)
st.caption(f"Red bars = the selected **{shift}** window ({SHIFT_WINDOWS[shift]}). Blue = all other hours.")

st.markdown("---")

# ============================================================================
# TOP ZONES FOR THIS WINDOW — real ranking from actual filtered violation
# counts, replacing the old page's fabricated latitude-band "patrol beats."
# ============================================================================
st.subheader(f"📍 Top Zones During {shift}")

top_zones = pd.DataFrame(data["top_zones"])
if top_zones.empty:
    st.caption("No zone data for this window.")
else:
    tier_colors = {
        "Critical": "#dc2626", "High Risk": "#f97316",
        "Medium Risk": "#eab308", "Low Risk": "#22c55e", "Unrated": "#94a3b8",
    }
    for _, row in top_zones.iterrows():
        color = tier_colors.get(row["risk_tier"], "#94a3b8")
        cols = st.columns([3, 1.2, 1, 1.3])
        cols[0].markdown(f"**{row['location'][:55]}**")
        cols[1].markdown(
            f"<span style='color:{color};font-weight:600;'>● {row['risk_tier']}</span>",
            unsafe_allow_html=True,
        )
        cols[2].markdown(f"{int(row['violations'])} this shift")
        cols[3].markdown(f"📍 {row['police_station']}")

st.markdown("---")

# ============================================================================
# WHAT'S DIFFERENT THIS SHIFT — violation type / vehicle type mix.
# This is the genuinely useful "time of day matters" insight: a morning
# shift's top violation types and vehicle mix are usually not the same as
# a night shift's, and now that's shown for real instead of implied.
# ============================================================================
st.subheader(f"🔍 What's Typical During {shift}")

mix_col1, mix_col2 = st.columns(2)

with mix_col1:
    st.caption("Top violation types")
    vt = pd.DataFrame(data["top_violation_types"])
    if not vt.empty:
        fig_vt = go.Figure(
            go.Bar(
                y=vt["violation_type"], x=vt["count"], orientation="h",
                marker_color="#3b82f6",
            )
        )
        fig_vt.update_layout(
            template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            height=260, margin=dict(t=10, r=10, l=10, b=10),
            yaxis=dict(autorange="reversed"),
        )
        st.plotly_chart(fig_vt, use_container_width=True)

with mix_col2:
    st.caption("Top vehicle types")
    vh = pd.DataFrame(data["top_vehicle_types"])
    if not vh.empty:
        fig_vh = go.Figure(
            go.Bar(
                y=vh["vehicle_type"], x=vh["count"], orientation="h",
                marker_color="#f97316",
            )
        )
        fig_vh.update_layout(
            template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            height=260, margin=dict(t=10, r=10, l=10, b=10),
            yaxis=dict(autorange="reversed"),
        )
        st.plotly_chart(fig_vh, use_container_width=True)

st.markdown("---")

# ============================================================================
# STATION LOAD — which stations carry this shift's enforcement load.
# ============================================================================
st.subheader(f"🏢 Station Load — {shift}")
stations = pd.DataFrame(data["top_stations"])
if not stations.empty:
    fig_st = go.Figure(
        go.Bar(x=stations["police_station"], y=stations["count"], marker_color="#8b5cf6")
    )
    fig_st.update_layout(
        template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        height=280, margin=dict(t=10, r=10, l=10, b=10),
        xaxis_title="Station", yaxis_title="Violations this shift",
    )
    st.plotly_chart(fig_st, use_container_width=True)