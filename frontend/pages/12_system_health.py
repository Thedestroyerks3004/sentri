import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from frontend.utils.api_client import get_system_health
from frontend.utils.ui import apply_brand, page_header

apply_brand()

page_header("Immune System - Enforcement Audit", "Dynamic Quality Scores (DQS), rejection pattern mining, and deviation alerts.")

data = get_system_health()
if data.get("error"):
    st.warning(f"System health unavailable: {data['error']}")
    st.stop()

st.metric("City Avg Rejection Rate", f"{data['city_avg_rejection']}%", delta=f"+/-{data['city_std_deviation']}% std dev")
st.markdown("---")

st.subheader("Deviation Alert Feed")
alerts = data.get("deviation_alerts", [])
if alerts:
    for a in alerts:
        color = "#ef4444" if a["severity"] == "CRITICAL" else "#f97316"
        st.markdown(
            f"<div style='background:#2a0e0e;border-left:4px solid {color};border-radius:4px;padding:10px 14px;margin:6px 0;font-size:13px;'>"
            f"<b>{a['station']}</b> - Rejection rate: {a['rejection_rate']}% (City avg: {data['city_avg_rejection']}%)<br>"
            f"<span style='color:#94a3b8;font-size:11px;'>{a['recommendation']}</span></div>",
            unsafe_allow_html=True)
else:
    st.caption("No stations deviating significantly from city average.")

st.markdown("---")

st.subheader("Station Quality Scores (DQS)")
stations = pd.DataFrame(data.get("stations", []))
if not stations.empty:
    stations["dqs_color"] = stations["dqs"].apply(lambda x: "#22c55e" if x >= 80 else ("#f0a500" if x >= 50 else "#ef4444"))
    col1, col2 = st.columns([2, 1])
    with col1:
        fig = go.Figure(go.Bar(
            y=stations["police_station"], x=stations["dqs"], orientation="h",
            marker_color=stations["dqs_color"], text=stations["dqs"].round(0).astype(int), textposition="outside"))
        fig.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                          height=max(400, len(stations) * 14), xaxis_title="Dynamic Quality Score", yaxis=dict(autorange="reversed"))
        st.plotly_chart(fig, use_container_width=True)
    with col2:
        weight = st.slider("Low-quality Source Penalty", 0, 100, 50)
        low_dqs = stations[stations["dqs"] < 50]
        st.metric("Stations below DQS 50", len(low_dqs))
        st.metric("Penalty active", f"{weight}%")

st.markdown("---")
st.subheader("Rejection Pattern Explorer")
officers = pd.DataFrame(data.get("officers", []))
if not officers.empty:
    fig2 = go.Figure()
    fig2.add_trace(go.Scatter(
        x=officers["created_by_id"].astype(str), y=officers["rejection_rate"],
        mode="markers",
        marker=dict(size=officers["total_filed"].clip(0, 50) / 2 + 5, color=officers["rejection_rate"],
                    colorscale="RdYlGn_r", showscale=True, colorbar=dict(title="Rejection %")),
        hovertemplate="Officer: %{x}<br>Rejection: %{y:.1f}%<br>Filed: %{marker.size:.0f}<extra></extra>"))
    fig2.add_hline(y=data["city_avg_rejection"], line_dash="dash", line_color="#f0a500", annotation_text=f"City avg: {data['city_avg_rejection']}%")
    fig2.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                       height=400, xaxis_title="Officer ID", yaxis_title="Rejection Rate (%)")
    st.plotly_chart(fig2, use_container_width=True)

st.markdown("---")
st.subheader("GPS Drift Zones")
gps = pd.DataFrame(data.get("gps_drift_zones", []))
if not gps.empty:
    st.dataframe(gps.rename(columns={"loc_key": "Location Key", "rejections": "Rejected Count", "location": "Address"}),
                 use_container_width=True, hide_index=True)
