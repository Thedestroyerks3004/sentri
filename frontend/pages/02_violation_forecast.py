import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from frontend.utils.api_client import get_forecast
from frontend.utils.ui import format_indian, page_header

page_header(
    "🔮 Violation Forecast",
    "Prophet predictions for the next 7 days — where enforcement is most needed, and when.",
)

LOCATIONS = {
    "city": "City-wide",
    "safina_plaza": "Safina Plaza Junction",
    "kr_market": "KR Market Junction",
    "elite": "Elite Junction",
    "sagar_theatre": "Sagar Theatre Junction",
    "central_street": "Central Street Junction",
}

# Same risk-tier palette used on the Daily Briefing page, so "how bad is
# this" reads consistently across SENTRI rather than introducing a new
# color vocabulary just for this page.
TIER_COLORS = {
    "Critical": "#dc2626",
    "High Risk": "#f97316",
    "Medium Risk": "#eab308",
    "Low Risk": "#22c55e",
}

# A location's hourly peak relative to its own 7-day mean. This is a
# self-contained signal (no new API/historical-average endpoint needed) --
# Prophet's own forecast already encodes the daily/weekly seasonality, so
# the ratio of peak-hour yhat to mean yhat over the window tells us how
# spiky vs. flat that location's week looks, without needing to know its
# absolute volume (a quiet junction and a busy one can both spike 2x).
RATIO_TIERS = [
    (1.8, "Critical"),
    (1.5, "High Risk"),
    (1.25, "Medium Risk"),
    (0.0, "Low Risk"),
]


def _tier_for_ratio(ratio: float) -> str:
    for threshold, tier in RATIO_TIERS:
        if ratio >= threshold:
            return tier
    return "Low Risk"


@st.cache_data(ttl=300, show_spinner=False)
def _load_all_forecasts(location_keys: tuple[str, ...]) -> dict[str, pd.DataFrame]:
    """One forecast fetch per location, cached 5 min so the risk scan
    doesn't refire 6 API calls on every widget interaction on this page."""
    out = {}
    for key in location_keys:
        data = get_forecast(key)
        df = pd.DataFrame(data.get("forecast", []))
        if not df.empty:
            df["ds"] = pd.to_datetime(df["ds"])
        out[key] = df
    return out


def _summarize(key: str, label: str, df: pd.DataFrame) -> dict | None:
    if df.empty:
        return None
    peak = df.loc[df["yhat"].idxmax()]
    mean_yhat = float(df["yhat"].mean())
    ratio = float(peak["yhat"]) / mean_yhat if mean_yhat > 0 else 1.0
    return {
        "key": key,
        "label": label,
        "peak_ds": peak["ds"],
        "peak_yhat": float(peak["yhat"]),
        "mean_yhat": mean_yhat,
        "ratio": ratio,
        "tier": _tier_for_ratio(ratio),
        "week_total": float(df["yhat"].sum()),
    }


all_forecasts = _load_all_forecasts(tuple(LOCATIONS.keys()))
summaries = [
    s for s in (
        _summarize(key, label, all_forecasts.get(key, pd.DataFrame()))
        for key, label in LOCATIONS.items()
        if key != "city"  # city-wide is a baseline reference, not a patrol target
    )
    if s is not None
]
summaries.sort(key=lambda s: s["ratio"], reverse=True)

# ============================================================================
# SECTION 1: RISK SCAN — which junctions need attention this week, ranked.
# Leads the page because the actual decision ("where do I deploy?") needs
# a comparison across locations, not one chart at a time.
# ============================================================================
st.subheader("📍 7-Day Risk Scan — Junctions Ranked by Spike Severity")
st.caption(
    "Ranked by how far each junction's predicted peak rises above its own 7-day average. "
    "A high ratio means a sharp, concentrated spike worth planning around — not necessarily the busiest junction overall."
)

if not summaries:
    st.warning("No forecast data available for any junction yet.")
    st.stop()

for s in summaries:
    color = TIER_COLORS[s["tier"]]
    cols = st.columns([3, 2, 2, 2, 2])
    cols[0].markdown(
        f"<span style='color:{color};font-weight:700;'>● {s['tier']}</span>  &nbsp; **{s['label']}**",
        unsafe_allow_html=True,
    )
    cols[1].metric("Peak", f"{s['peak_yhat']:.0f}/hr", label_visibility="visible")
    cols[2].metric("vs. avg", f"{s['ratio']:.2f}×")
    cols[3].metric("Peak time", s["peak_ds"].strftime("%a %H:%M"))
    cols[4].metric("7-day total", format_indian(round(s["week_total"])))

st.markdown("---")

# ============================================================================
# SECTION 2: DRILL-DOWN — defaults to the riskiest junction from the scan,
# but any location (including City-wide) can be inspected directly.
# ============================================================================
st.subheader("🔍 Junction Detail")

default_key = summaries[0]["key"] if summaries else "city"
loc = st.selectbox(
    "Location",
    list(LOCATIONS.keys()),
    index=list(LOCATIONS.keys()).index(default_key),
    format_func=lambda k: LOCATIONS[k],
)

fc = all_forecasts.get(loc, pd.DataFrame())
if fc.empty:
    st.warning("No forecast available for this location.")
    st.stop()

peak = fc.loc[fc["yhat"].idxmax()]
mean_yhat = float(fc["yhat"].mean())
peak_ratio = float(peak["yhat"]) / mean_yhat if mean_yhat > 0 else 1.0
avg_band = float((fc["yhat_upper"] - fc["yhat_lower"]).abs().mean())

c1, c2, c3, c4 = st.columns(4)
c1.metric("Peak predicted hour", peak["ds"].strftime("%a %d %b, %H:%M"))
c2.metric("Peak volume", f"{peak['yhat']:.0f}/hr", f"{peak_ratio:.2f}× this location's 7-day avg")
c3.metric("7-day total (predicted)", format_indian(round(fc["yhat"].sum())))
c4.metric("Typical uncertainty", f"±{avg_band / 2:.0f}/hr")

fig = go.Figure()
fig.add_trace(
    go.Scatter(
        x=fc["ds"], y=fc["yhat"], name="Predicted",
        line=dict(color="#3b82f6", width=2),
    )
)
fig.add_trace(
    go.Scatter(x=fc["ds"], y=fc["yhat_upper"], line=dict(width=0), fill=None, showlegend=False)
)
fig.add_trace(
    go.Scatter(
        x=fc["ds"], y=fc["yhat_lower"], fill="tonexty", name="Confidence interval",
        fillcolor="rgba(59,130,246,0.18)", line=dict(width=0),
    )
)
fig.add_hline(
    y=mean_yhat, line_dash="dot", line_color="rgba(255,255,255,0.4)",
    annotation_text="7-day average", annotation_position="bottom right",
)
fig.update_layout(
    template="plotly_dark",
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    height=440,
    title=all_forecasts and LOCATIONS[loc],
    margin=dict(t=40),
    xaxis_title="Date / time",
    yaxis_title="Predicted violations per hour",
)
st.plotly_chart(fig, use_container_width=True)

# ============================================================================
# SECTION 3: ACTIONABLE WINDOWS — real upcoming hours that justify a
# deploy decision, replacing the old hardcoded example sentence.
# ============================================================================
st.subheader("🚓 Upcoming Windows Worth Planning Around")

ALERT_RATIO_THRESHOLD = 1.4
fc_alerts = fc.copy()
fc_alerts["ratio_to_avg"] = fc_alerts["yhat"] / mean_yhat if mean_yhat > 0 else 1.0
spikes = (
    fc_alerts[fc_alerts["ratio_to_avg"] >= ALERT_RATIO_THRESHOLD]
    .sort_values("yhat", ascending=False)
    .head(8)
)

if spikes.empty:
    st.caption(
        f"No hours in the next 7 days for {LOCATIONS[loc]} are forecast to exceed "
        f"{ALERT_RATIO_THRESHOLD:.1f}× the location's own average — a relatively flat week."
    )
else:
    display = spikes[["ds", "yhat", "ratio_to_avg"]].copy()
    display["ds"] = display["ds"].dt.strftime("%a %d %b, %H:%M")
    display["yhat"] = display["yhat"].round(0).astype(int)
    display["ratio_to_avg"] = display["ratio_to_avg"].round(2).astype(str) + "×"
    display.columns = ["When", "Predicted volume", "vs. average"]
    st.dataframe(display, use_container_width=True, hide_index=True)
    st.caption(
        f"These are the hours where {LOCATIONS[loc]} is predicted to run at "
        f"{ALERT_RATIO_THRESHOLD:.1f}× its normal load or higher — the strongest candidates "
        "for pre-planned patrol coverage rather than reactive dispatch."
    )