import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from frontend.utils.api_client import get_commercial_impact
from frontend.utils.ui import format_indian, page_header

page_header(
    "💼 Commercial Impact",
    "Weekly fine revenue and delivery-delay cost by zone.",
)

data = get_commercial_impact()
if data.get("error"):
    st.warning(data["error"])
    st.stop()

by_zone = pd.DataFrame(data.get("by_zone", []))
if by_zone.empty:
    st.info("No commercial impact data is available yet.")
    st.stop()

by_zone["fine_revenue"] = by_zone["fine_revenue"].fillna(0)
by_zone["delay_cost"] = by_zone["delay_cost"].fillna(0)
by_zone["total_cost"] = by_zone["fine_revenue"] + by_zone["delay_cost"]
by_zone = by_zone.sort_values("total_cost", ascending=False)

city_total = float(by_zone["total_cost"].sum())
top8 = by_zone.head(8).copy()

# Zone labels in this dataset are full postal addresses (e.g. "18th Main
# Road, Block 2, Koramangala, Bengaluru, Karnataka. Pin-560068 (India)") --
# trim to the first segment or two for axis labels, full address stays
# available in the hover tooltip.
def _short_label(zone: str, max_segments: int = 2) -> str:
    parts = [p.strip() for p in str(zone).split(",") if p.strip()]
    return ", ".join(parts[:max_segments]) if parts else str(zone)


top8["short_label"] = top8["zone"].apply(_short_label)
top8["share_of_city_pct"] = (top8["total_cost"] / city_total * 100) if city_total > 0 else 0

# ============================================================================
# HEADLINE METRICS
# ============================================================================
col1, col2, col3, col4 = st.columns(4)
col1.metric("Weekly fine revenue", f"₹{format_indian(data.get('weekly_fine_revenue', 0))}")
col2.metric("Weekly delay cost", f"₹{format_indian(data.get('weekly_delay_cost', 0))}")
col3.metric("Commercial vehicles flagged", f"{data.get('commercial_vehicles_flagged', 0):,}")

top_zone_raw = data.get("top_cost_zone", "N/A")
top_zone_label = _short_label(top_zone_raw) if top_zone_raw != "N/A" else "N/A"
col4.metric("Top cost zone", top_zone_label, help=top_zone_raw if top_zone_raw != "N/A" else None)

st.markdown("---")

# ============================================================================
# RANKED IMPACT — horizontal stacked bars, sorted by total cost.
#
# Why this shape instead of the old grouped vertical bars:
#  - Fine revenue and delay cost are derived very differently (fine = sum
#    of fixed per-offence amounts; delay cost = a modeled commercial-delay
#    estimate), so putting them side by side per zone invited a "which bar
#    is taller" read that mostly reflects unit-scale, not anything
#    meaningful about the zone. Stacking shows each zone's *total* cost as
#    one number, with the fine/delay split visible inside it.
#  - Zone labels are long addresses; horizontal bars give them room to
#    read on the y-axis instead of cramming under rotated x-axis text.
#  - Sorted descending so the chart doubles as a priority list, matching
#    how ranking already works elsewhere in this app (patrol priorities,
#    forecast risk scan).
# ============================================================================
st.subheader("📊 Top Zones by Total Commercial Cost")
st.caption(
    "Each bar is total weekly cost at that zone — fine revenue plus estimated delivery-delay cost. "
    "Sorted highest to lowest."
)

fig = go.Figure()
fig.add_trace(
    go.Bar(
        y=top8["short_label"],
        x=top8["fine_revenue"],
        name="Fine revenue",
        orientation="h",
        marker_color="#3b82f6",
        customdata=top8[["zone", "share_of_city_pct"]],
        hovertemplate=(
            "<b>%{customdata[0]}</b><br>Fine revenue: ₹%{x:,.0f}<extra></extra>"
        ),
    )
)
fig.add_trace(
    go.Bar(
        y=top8["short_label"],
        x=top8["delay_cost"],
        name="Delay cost",
        orientation="h",
        marker_color="#f97316",
        customdata=top8[["zone", "share_of_city_pct"]],
        hovertemplate=(
            "<b>%{customdata[0]}</b><br>Delay cost: ₹%{x:,.0f}"
            "<br>Share of city total: %{customdata[1]:.1f}%<extra></extra>"
        ),
    )
)
fig.update_layout(
    template="plotly_dark",
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    height=420,
    barmode="stack",
    margin=dict(t=30, r=20, l=10, b=10),
    xaxis_title="INR",
    yaxis=dict(autorange="reversed"),  # highest-cost zone on top
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
)
st.plotly_chart(fig, use_container_width=True)

# ============================================================================
# SHARE OF CITY TOTAL — answers "how concentrated is this cost" at a
# glance, which the original page never showed: a bare rupee number means
# little without knowing what fraction of the citywide total it represents.
# ============================================================================
if city_total > 0:
    top3_share = top8.head(3)["total_cost"].sum() / city_total * 100
    concentration_note = (
        "concentration this high is usually worth a targeted enforcement pass rather than spreading effort evenly."
        if top3_share >= 40
        else "cost is fairly distributed across zones rather than concentrated in a few hotspots."
    )
    st.caption(
        f"The top 3 zones shown account for **{top3_share:.0f}%** of citywide commercial impact cost "
        f"(₹{format_indian(round(city_total))} total across {len(by_zone)} zones) — {concentration_note}"
    )

st.markdown("---")

# ============================================================================
# DATA QUALITY CAVEAT — uncategorized_offence_rows means some violations
# didn't map to a known fine category and were defaulted, so the revenue
# figures above are an approximation, not an exact ledger. Worth surfacing
# rather than presenting the totals as if they were complete.
# ============================================================================
uncategorized = data.get("uncategorized_offence_rows", 0)
if uncategorized:
    st.warning(
        f"⚠️ **{format_indian(uncategorized)} violation records** had no matching offence-category rule "
        "and were defaulted to the 'other' fine bucket for this estimate. Treat the totals above as a "
        "close approximation, not an exact ledger — adding a category rule for these offence types "
        "(see `VTYPE_CATEGORY_MAP` in the training pipeline) will sharpen the numbers."
    )

st.caption(data.get("methodology_note", ""))