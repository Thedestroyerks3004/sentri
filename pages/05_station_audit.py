import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
import streamlit as st

from utils.api_client import get_station_performance
from utils.ui import page_header, wow_moment

page_header("📊 Station Audit", "Rejection rate = rejected ÷ (approved + rejected).")

data = get_station_performance()
stations = pd.DataFrame(data["stations"])
city_avg = data["city_avg"]

st.metric("City average rejection rate", f"{city_avg}%")

kod = stations[stations["police_station"].str.contains("Kodigehalli", case=False, na=False)]
if not kod.empty:
    wow_moment(
        f"<b>Kodigehalli</b> — <b>{kod.iloc[0]['rejection_rate']:.1f}%</b> rejection rate. "
        "Four in ten challans wasted. 500 days of officer time lost city-wide in 5 months."
    )

plot_df = stations[stations["total"] >= 100].copy()
plot_df["tier"] = plot_df["rejection_rate"].apply(
    lambda r: "high" if r >= city_avg * 1.2 else ("medium" if r >= city_avg * 0.8 else "low")
)
sorted_df = plot_df.sort_values("rejection_rate")

fig_bar = go.Figure(go.Bar(
    y=sorted_df["police_station"], x=sorted_df["rejection_rate"], orientation="h",
    marker_color=sorted_df["tier"].map({"high": "#ef4444", "medium": "#f59e0b", "low": "#22c55e"}),
    text=sorted_df["rejection_rate"].round(1), texttemplate="%{text}%", textposition="outside",
))
fig_bar.add_vline(x=city_avg, line_dash="dash", line_color="#f8fafc", annotation_text=f"City avg {city_avg}%")
fig_bar.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      height=max(500, len(plot_df) * 18), margin=dict(t=40))
st.plotly_chart(fig_bar, use_container_width=True)

fig_scatter = px.scatter(
    plot_df, x="total", y="rejection_rate", hover_name="police_station",
    size="rejected", color="tier",
    color_discrete_map={"high": "#ef4444", "medium": "#f59e0b", "low": "#22c55e"},
)
fig_scatter.add_hline(y=city_avg, line_dash="dash", line_color="#94a3b8")
fig_scatter.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", height=420)
st.plotly_chart(fig_scatter, use_container_width=True)

c1, c2 = st.columns(2)
with c1:
    st.subheader("Top 5 — highest rejection")
    st.dataframe(stations.head(5), use_container_width=True, hide_index=True)
with c2:
    st.subheader("Bottom 5 — lowest rejection")
    st.dataframe(stations.tail(5), use_container_width=True, hide_index=True)
