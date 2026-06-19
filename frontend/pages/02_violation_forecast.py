import plotly.graph_objects as go
import pandas as pd
import streamlit as st

from frontend.utils.api_client import get_forecast
from frontend.utils.ui import page_header

page_header(
    "🔮 Violation Forecast",
    "Prophet predictions for the next 7 days — city-wide and top junctions.",
)

LOCATIONS = {
    "city": "City-wide",
    "safina_plaza": "Safina Plaza Junction",
    "kr_market": "KR Market Junction",
    "elite": "Elite Junction",
    "sagar_theatre": "Sagar Theatre Junction",
    "central_street": "Central Street Junction",
}

loc = st.selectbox("Location", list(LOCATIONS.keys()), format_func=lambda k: LOCATIONS[k])
data = get_forecast(loc)
fc = pd.DataFrame(data["forecast"])

if fc.empty:
    st.warning("No forecast available for this location.")
    st.stop()

fc["ds"] = pd.to_datetime(fc["ds"])
peak = fc.loc[fc["yhat"].idxmax()]
c1, c2, c3 = st.columns(3)
c1.metric("Peak predicted hour", peak["ds"].strftime("%a %d %b %H:%M"))
c2.metric("Peak volume", f"{peak['yhat']:.0f}")
c3.metric("7-day total (predicted)", f"{fc['yhat'].sum():.0f}")

fig = go.Figure()
fig.add_trace(go.Scatter(x=fc["ds"], y=fc["yhat"], name="Predicted", line=dict(color="#3b82f6", width=2)))
fig.add_trace(go.Scatter(x=fc["ds"], y=fc["yhat_upper"], line=dict(width=0), showlegend=False))
fig.add_trace(go.Scatter(
    x=fc["ds"], y=fc["yhat_lower"], fill="tonexty", name="Confidence interval",
    fillcolor="rgba(59,130,246,0.2)", line=dict(width=0),
))
fig.update_layout(
    template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    height=480, title=data.get("label", LOCATIONS[loc]), margin=dict(t=40),
    xaxis_title="Date/time", yaxis_title="Predicted violations per hour",
)
st.plotly_chart(fig, use_container_width=True)

st.info(
    "Forecasts feed the Daily Briefing and Patrol Map. "
    "A spike tomorrow at 4 AM at Safina Plaza → deploy officers tonight."
)
