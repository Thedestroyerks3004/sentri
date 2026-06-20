import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from frontend.utils.api_client import get_analytics_explorer
from frontend.utils.ui import apply_brand, page_header

apply_brand()

page_header("Analytics Explorer", "DBSCAN micro-clusters, vehicle-type association rules, and anomaly explanations.")

data = get_analytics_explorer()
if data.get("error"):
    st.warning(f"Analytics unavailable: {data['error']}")
    st.stop()

tab1, tab2, tab3, tab4 = st.tabs([
    "Micro-Zone Clusters", "Association Rules", "Anomaly Explanations", "Station Digitization"
])

with tab1:
    st.subheader("High-Density Micro-Zones (DBSCAN-style)")
    clusters = pd.DataFrame(data.get("clusters", []))
    if not clusters.empty:
        fig = go.Figure()
        fig.add_trace(go.Scattermapbox(
            lat=clusters["latitude"], lon=clusters["longitude"],
            mode="markers",
            marker=dict(size=clusters["violation_count"].clip(0, 100) / 5 + 5,
                       color=clusters["violation_count"], colorscale="Hot", showscale=True,
                       colorbar=dict(title="Violations")),
            text=clusters["location"],
            hovertemplate="<b>%{text}</b><br>Violations: %{marker.size:.0f}<br>Diversity: %{customdata[0]} types<extra></extra>",
            customdata=clusters[["vehicle_diversity"]],
        ))
        fig.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                         mapbox=dict(style="carto-darkmatter", center=dict(lat=clusters["latitude"].mean(), lon=clusters["longitude"].mean()),
                                    zoom=10), height=500, margin=dict(t=10, r=10, l=10, b=10))
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No cluster data available.")

with tab2:
    st.subheader("Vehicle-Type Association Rules")
    rules = data.get("association_rules", [])
    if rules:
        rules_df = pd.DataFrame(rules)
        fig2 = go.Figure(go.Bar(
            x=rules_df["confidence"], y=rules_df["violation_type"],
            orientation="h",
            marker_color=rules_df["confidence"],
            marker_colorscale="Viridis",
            customdata=rules_df[["vehicle_type", "support"]],
            hovertemplate="<b>%{y}</b><br>Confidence: %{x:.1%}<br>Vehicle: %{customdata[0]}<br>Support: %{customdata[1]} rows<extra></extra>",
        ))
        fig2.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                          height=max(400, len(rules_df) * 20),
                          xaxis_title="Confidence", xaxis_tickformat=".0%", yaxis=dict(autorange="reversed"))
        st.plotly_chart(fig2, use_container_width=True)
    else:
        st.info("No association rules found.")

with tab3:
    st.subheader("Anomaly Explanations")
    explanations = data.get("anomaly_explanations", [])
    if explanations:
        for e in explanations[:20]:
            color = "#ef4444" if e["anomaly_score"] > 0.8 else ("#f97316" if e["anomaly_score"] > 0.6 else "#f0a500")
            st.markdown(
                f"<div style='background:#111318;border:1px solid #1C2030;border-left:4px solid {color};"
                f"border-radius:4px;padding:10px 14px;margin:6px 0;font-size:12px;'>"
                f"<b>{e['officer_id']}</b> at <b>{e['police_station']}</b> "
                f"<span style='color:{color};'>(score: {e['anomaly_score']})</span><br>"
                f"<span style='color:#94a3b8;'>{' | '.join(e['reasons'][:3])}</span><br>"
                f"<span style='color:#6e7681;font-size:10px;'>{e['location'][:60]}</span></div>",
                unsafe_allow_html=True)
    else:
        st.info("No anomaly explanations available.")

with tab4:
    st.subheader("Station Digitization Rate")
    digit = pd.DataFrame(data.get("station_digitization", []))
    if not digit.empty:
        digit = digit.sort_values("digitization_rate", ascending=False)
        fig3 = go.Figure(go.Bar(
            x=digit["digitization_rate"], y=digit["police_station"],
            orientation="h",
            marker_color=digit["digitization_rate"],
            marker_colorscale="Blues",
            text=digit["digitization_rate"].round(1).astype(str) + "%", textposition="outside",
        ))
        fig3.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                          height=max(400, len(digit) * 16),
                          xaxis_title="Digitization Rate (%)", yaxis=dict(autorange="reversed"))
        st.plotly_chart(fig3, use_container_width=True)
    else:
        st.info("No digitization data available.")
