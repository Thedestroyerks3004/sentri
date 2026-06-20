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

# Only Critical / High Risk zones go in the side list -- this page's job
# is "where's actually dangerous right now," not every zone in the result
# set. Ranked by live activity first (what's happening this window),
# predicted volume second.
high_risk_df = (
    df[df["risk_tier"].isin(["Critical", "High Risk"])]
    .sort_values(["violations_at_hour", "predicted_today"], ascending=False)
)

if "selected_loc" not in st.session_state or st.session_state.selected_loc not in df["loc_key"].values:
    st.session_state.selected_loc = (
        high_risk_df.iloc[0]["loc_key"] if not high_risk_df.empty else df.iloc[0]["loc_key"]
    )

map_col, panel_col = st.columns([2.2, 1])

MAP_HEIGHT = 640

with map_col:
    # A fixed zoom_start around the dataframe's median point silently fails
    # whenever the result set includes even one outlier far from the main
    # cluster (e.g. a zone out past Ramanagara/Kanakapura) -- the median
    # shifts toward open country and zoom 12 shows mostly empty terrain
    # with no markers in view, which is exactly the symptom in the
    # screenshot. fit_bounds() instead frames the map to whatever points
    # are actually being shown, every time, regardless of how the result
    # set's geography happens to be distributed.
    m = folium.Map(tiles="CartoDB dark_matter")
    sw = [df["latitude"].min(), df["longitude"].min()]
    ne = [df["latitude"].max(), df["longitude"].max()]
    if sw == ne:
        # Single-point result set: fit_bounds on an identical sw/ne pair
        # doesn't zoom in at all, so fall back to a tight manual zoom.
        m.location = sw
        m.zoom_start = 14
    else:
        m.fit_bounds([sw, ne], padding=(30, 30))

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
    loc_key_by_coord = {}
    for _, row in df.iterrows():
        intensity = row["violations_at_hour"] / max_v
        radius = 6 + intensity * 22
        color = row["risk_color"]
        is_selected = row["loc_key"] == st.session_state.selected_loc
        weight = 5 if is_selected else (4 if row.get("priority_patrol") else 2)
        opacity = 1.0 if is_selected else (0.9 if row.get("priority_patrol") else 0.7)

        future_peak = row.get("peak_window", "N/A")
        lat_disp = f"{row['latitude']:.5f}"
        lon_disp = f"{row['longitude']:.5f}"
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
        <i>{row['patrol_recommendation']}</i><br>
        <span style='color:#94a3b8;font-size:0.8rem;'>📍 {lat_disp}, {lon_disp}</span>
        </div>
        """
        folium.CircleMarker(
            location=[row["latitude"], row["longitude"]],
            radius=radius,
            color="#ffffff" if is_selected else color,
            weight=weight,
            fill=True,
            fill_color=color,
            fill_opacity=opacity,
            popup=folium.Popup(popup_html, max_width=340),
            tooltip=row["zone_name"][:40],
        ).add_to(m)
        loc_key_by_coord[(round(row["latitude"], 5), round(row["longitude"], 5))] = row["loc_key"]

        if row.get("priority_patrol"):
            folium.CircleMarker(
                location=[row["latitude"], row["longitude"]],
                radius=radius + 8,
                color="#ef4444",
                weight=1,
                fill=False,
                opacity=0.6,
            ).add_to(m)

    map_result = st_folium(m, width=None, height=MAP_HEIGHT, returned_objects=["last_object_clicked"])

    if map_result and map_result.get("last_object_clicked"):
        click = map_result["last_object_clicked"]
        if click:
            lat, lng = click.get("lat"), click.get("lng")
            if lat is not None and lng is not None:
                dist = ((df["latitude"] - lat) ** 2 + (df["longitude"] - lng) ** 2) ** 0.5
                nearest_idx = dist.idxmin()
                if dist.loc[nearest_idx] < 0.01:
                    clicked_loc_key = df.loc[nearest_idx, "loc_key"]
                    if clicked_loc_key != st.session_state.selected_loc:
                        st.session_state.selected_loc = clicked_loc_key
                        st.rerun()

with panel_col:
    # Matches the panel's scrollable area to the map's render height, so
    # neither column trails off into empty background below the other.
    panel_container = st.container(height=MAP_HEIGHT, border=False)

with panel_container:
    st.markdown(f"#### 🔴 High-Risk Places ({len(high_risk_df)})")

    if high_risk_df.empty:
        st.caption("No Critical or High Risk zones in this window.")
    else:
        # st.expander has no built-in on-open callback, and calling
        # st.rerun() mid-loop (before the remaining expanders have even
        # rendered) is unsafe -- it would cut the render short. Instead,
        # each expander gets a small "Focus on map" button that's the
        # actual trigger for changing selected_loc; the expander's own
        # open/closed state is left to Streamlit, and only the selected
        # card defaults to expanded.
        for _, row in high_risk_df.iterrows():
            is_selected = row["loc_key"] == st.session_state.selected_loc
            tier_dot = "🔴" if row["risk_tier"] == "Critical" else "🟠"
            header = (
                f"{tier_dot} {row['zone_name'][:42]} — "
                f"{int(row['violations_at_hour'])} now"
            )
            with st.expander(header, expanded=is_selected):
                if not is_selected:
                    if st.button("📍 Focus on map", key=f"focus_{row['loc_key']}"):
                        st.session_state.selected_loc = row["loc_key"]
                        st.rerun()

                detail_lat = row.get("latitude")
                detail_lon = row.get("longitude")
                maps_link = ""
                if detail_lat is not None and detail_lon is not None:
                    maps_link = (
                        f"<a href='https://www.google.com/maps?q={detail_lat},{detail_lon}' "
                        f"target='_blank' style='color:#60a5fa;font-size:0.85rem;'>"
                        f"Open in Google Maps ↗</a>"
                    )

                st.markdown(
                    f"<span style='color:{row['risk_color']};font-weight:700;'>{row['risk_tier']}</span><br>"
                    f"<span style='color:#94a3b8;font-size:0.85rem;'>{row['location'][:120]}</span>",
                    unsafe_allow_html=True,
                )
                st.markdown(
                    f"**Violations at this window:** {int(row['violations_at_hour'])}  \n"
                    f"**Total at spot:** {int(row['total_violations']):,}  \n"
                    f"**PCIS:** {row['pcis']}  \n"
                    f"**Peak window:** {row['peak_window']}  \n"
                    f"**Top violation:** {row['top_violation']}  \n"
                    f"**Dominant vehicle:** {row['top_vehicle']}  \n"
                    f"**Predicted today:** {int(row['predicted_today'])}  \n"
                    f"**Station:** {row['police_station']}"
                )
                if maps_link:
                    st.markdown(maps_link, unsafe_allow_html=True)
                st.markdown(
                    f"<p style='margin-top:0.5rem;font-style:italic;color:#60a5fa;'>"
                    f"{row['patrol_recommendation']}</p>",
                    unsafe_allow_html=True,
                )

                forecast_zone = get_zone_detail(row["loc_key"])
                if forecast_zone.get("forecast"):
                    fc = pd.DataFrame(forecast_zone["forecast"])
                    fc["ds"] = pd.to_datetime(fc["ds"])
                    fig = go.Figure(
                        go.Scatter(x=fc["ds"], y=fc["yhat"], line=dict(color="#3b82f6"), name="Forecast")
                    )
                    fig.update_layout(
                        template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                        height=180, margin=dict(t=20, b=20, l=20, r=20),
                        title=dict(text="Mini forecast", font=dict(size=12)),
                    )
                    st.plotly_chart(fig, use_container_width=True, key=f"fc_{row['loc_key']}")

if patrol_tonight and not df.empty:
    top5 = df[df["priority_patrol"] == True].head(5) if "priority_patrol" in df.columns else df.head(5)
    st.info(
        "**Priority patrol (next 3 hours):** "
        + " · ".join(f"{r['zone_name'][:30]} ({r['risk_tier']})" for _, r in top5.iterrows())
    )