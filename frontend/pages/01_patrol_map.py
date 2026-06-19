import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import folium
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from streamlit_folium import st_folium

from frontend.utils.api_client import get_patrol_map, get_zone_detail
from frontend.utils.ui import apply_brand

apply_brand()

DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
DAY_FULL = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _fmt_clock(hour: int) -> str:
    h = int(hour) % 24
    suffix = "AM" if h < 12 else "PM"
    display = h if h < 12 else h - 12
    if display == 0:
        display = 12
    return f"{display}:00 {suffix}"

if "map_day" not in st.session_state:
    st.session_state.map_day = 0
if "selected_loc" not in st.session_state:
    st.session_state.selected_loc = None

st.markdown('<p class="patrol-question">Where should I patrol tonight?</p>', unsafe_allow_html=True)

mode_col, time_col = st.columns([1, 2])
with mode_col:
    patrol_tonight = st.toggle(
        "🌙 Patrol tonight mode",
        value=True,
        help="Auto-filters to the next 3 hours from now. Top 5 zones highlighted.",
    )
with time_col:
    if patrol_tonight:
        st.caption("Using live IST time — the map shows now + next 2 hours and highlights likely hotspots.")
    else:
        st.caption("Manual exploration mode — use day buttons and hour slider below.")

# Day of week buttons
st.markdown("**Day of week**")
day_cols = st.columns(7)
for i, label in enumerate(DAYS):
    if day_cols[i].button(label, key=f"dow_{i}", use_container_width=True,
                          disabled=patrol_tonight):
        st.session_state.map_day = i

if not patrol_tonight:
    hour = st.slider("Hour of day", 0, 23, 5, format="%d:00")
else:
    hour = 5

search = st.text_input(
    "🔍 Search junction or police station",
    placeholder="Safina Plaza, Kodigehalli, Upparpet…",
)

data = get_patrol_map(
    hour=hour,
    day=st.session_state.map_day,
    limit=200,
    patrol_tonight=patrol_tonight,
    search=search or None,
)
markers = data["markers"]

if not markers:
    st.warning(
        f"No violations recorded for {data['day']} at hour {data['hour']:02d}:00. "
        f"Try another hour or day."
    )
    st.stop()

df = pd.DataFrame(markers)

now_label = data.get("now_ist", "")
if patrol_tonight:
    st.caption(
        f"Showing **{data['total_shown']}** candidate zones for **now + next 2 hours** · {now_label}"
    )
else:
    st.caption(
        f"Showing **{data['total_shown']}** zones for **{data['day']}** at **{_fmt_clock(data['hour'])}** · {now_label}"
    )

map_col, panel_col = st.columns([2.2, 1])

with map_col:
    center_lat = df["latitude"].median()
    center_lon = df["longitude"].median()
    m = folium.Map(location=[center_lat, center_lon], zoom_start=12, tiles="CartoDB dark_matter")

    # add subtle hotspot legend
    legend_html = """
    <div style='position:fixed; bottom:10px; right:10px; z-index:9999; background:white; color:black;
    padding:8px 10px; border-radius:6px; font-size:12px; box-shadow: 0 0 6px rgba(0,0,0,0.3);'>
      <b>Hotspot intensity</b><br>
      <span style='color:#ef4444'>●</span> Priority now<br>
      <span style='color:#3b82f6'>●</span> High forecast / future peak
    </div>
    """
    m.get_root().html.add_child(folium.Element(legend_html))

    max_v = df["violations_at_hour"].max() or 1
    for _, row in df.iterrows():
        intensity = row["violations_at_hour"] / max_v
        radius = 6 + intensity * 22
        color = row["risk_color"]
        weight = 4 if row.get("priority_patrol") else 2
        opacity = 0.9 if row.get("priority_patrol") else 0.7

        future_peak = row.get("peak_window", "N/A")
        popup_html = f"""
        <div style='min-width:240px;font-family:sans-serif;'>
        <b>{row['zone_name']}</b><br>
        <span style='color:{color};font-weight:bold;'>{row['risk_tier']}</span><br>
        <b>{row['violations_at_hour']:,}</b> violations at selected window<br>
        <b>{row['total_violations']:,}</b> total at this spot<br>
        Peak window: {future_peak}<br>
        Top type: {row['top_violation']}<br>
        Vehicle: {row['top_vehicle']}<br>
        Predicted today: <b>{int(row['predicted_today'])}</b><br>
        <i>{row['patrol_recommendation']}</i>
        </div>
        """
        folium.CircleMarker(
            location=[row["latitude"], row["longitude"]],
            radius=radius,
            color=color,
            weight=weight,
            fill=True,
            fill_color=color,
            fill_opacity=opacity,
            popup=folium.Popup(popup_html, max_width=340),
            tooltip=row["zone_name"][:40],
        ).add_to(m)

        if row.get("priority_patrol"):
            folium.CircleMarker(
                location=[row["latitude"], row["longitude"]],
                radius=radius + 8,
                color="#ef4444",
                weight=1,
                fill=False,
                opacity=0.6,
            ).add_to(m)

    map_result = st_folium(m, width=None, height=580, returned_objects=["last_object_clicked"])

    if map_result and map_result.get("last_object_clicked"):
        click = map_result["last_object_clicked"]
        if click:
            lat, lng = click.get("lat"), click.get("lng")
            if lat and lng:
                dist = ((df["latitude"] - lat) ** 2 + (df["longitude"] - lng) ** 2) ** 0.5
                nearest = df.loc[dist.idxmin()]
                if dist.min() < 0.01:
                    st.session_state.selected_loc = nearest["loc_key"]

with panel_col:
    st.markdown("#### Zone Intelligence")

    top_now = df.sort_values(["violations_at_hour", "pcis"], ascending=False).head(5)
    top_future = df.sort_values(["predicted_today", "pcis"], ascending=False).head(5)

    st.caption("Top hotspots now")
    for _, r in top_now.iterrows():
        st.write(f"• {r['zone_name']} ({int(r['violations_at_hour'])} at current window)")

    st.caption("Top hotspots for future peak")
    for _, r in top_future.iterrows():
        st.write(f"• {r['zone_name']} ({r['peak_window']}, {int(r['predicted_today'])} predicted)")

    st.markdown("---")

    zone_options = {f"{r['zone_name'][:45]}": r["loc_key"] for _, r in df.iterrows()}
    pick = st.selectbox(
        "Select zone",
        options=list(zone_options.keys()),
        index=0,
    )
    if st.session_state.selected_loc is None:
        st.session_state.selected_loc = zone_options[pick]
    elif st.session_state.selected_loc in zone_options.values():
        pass
    else:
        st.session_state.selected_loc = zone_options[pick]

    manual_pick = zone_options.get(pick)
    if manual_pick:
        st.session_state.selected_loc = manual_pick

    detail = get_zone_detail(st.session_state.selected_loc)

    tier_class = {
        "Critical": "tier-critical",
        "High Risk": "tier-high",
        "Medium Risk": "tier-medium",
        "Low Risk": "tier-low",
    }.get(detail["risk_tier"], "")

    st.markdown(
        f"<div class='zone-panel'>"
        f"<p class='{tier_class}'>{detail['risk_tier']}</p>"
        f"<h4 style='margin:0.25rem 0;'>{detail['zone_name']}</h4>"
        f"<p style='color:#94a3b8;font-size:0.85rem;'>{detail['location'][:120]}</p>"
        f"<hr style='border-color:#334155;'>"
        f"<b>Violations at selected hour:</b> {detail.get('violations_at_hour', '—')}<br>"
        f"<b>Total at spot:</b> {detail['total_violations']:,}<br>"
        f"<b>PCIS:</b> {detail['pcis']}<br>"
        f"<b>Peak window:</b> {detail['peak_window']}<br>"
        f"<b>Top violation:</b> {detail['top_violation']}<br>"
        f"<b>Dominant vehicle:</b> {detail['top_vehicle']}<br>"
        f"<b>Predicted today:</b> {int(detail['predicted_today'])}<br>"
        f"<b>Station:</b> {detail['police_station']}<br>"
        f"<p style='margin-top:0.75rem;font-style:italic;color:#60a5fa;'>"
        f"{detail['patrol_recommendation']}</p>"
        f"</div>",
        unsafe_allow_html=True,
    )

    if detail.get("forecast"):
        fc = pd.DataFrame(detail["forecast"])
        fc["ds"] = pd.to_datetime(fc["ds"])
        fig = go.Figure(go.Scatter(x=fc["ds"], y=fc["yhat"], line=dict(color="#3b82f6"), name="Forecast"))
        fig.update_layout(
            template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            height=200, margin=dict(t=20, b=20, l=20, r=20),
            title=dict(text="Mini forecast", font=dict(size=12)),
        )
        st.plotly_chart(fig, use_container_width=True)

if patrol_tonight and not df.empty:
    top5 = df[df["priority_patrol"] == True].head(5) if "priority_patrol" in df.columns else df.head(5)
    st.info(
        "**Priority patrol (next 3 hours):** "
        + " · ".join(f"{r['zone_name'][:30]} ({r['risk_tier']})" for _, r in top5.iterrows())
    )

