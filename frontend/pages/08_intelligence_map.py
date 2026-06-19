import folium
import pandas as pd
import streamlit as st
from folium.plugins import AntPath, HeatMap, MarkerCluster
from pathlib import Path
from streamlit_folium import st_folium

from frontend.utils.ui import apply_brand, page_header

ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS = ROOT / "artifacts"

apply_brand()
page_header(
    "🗺 Intelligence Map",
    "Explore five interactive layers for violations, patrol deployment, and delivery risk.",
)

BLR_LAT = 12.9716
BLR_LON = 77.5946

# ── Helpers ───────────────────────────────────────────────────────────────────

def find_col(df: pd.DataFrame, *keywords) -> str | None:
    """Return the first column name whose lowercase form contains any keyword."""
    for kw in keywords:
        for col in df.columns:
            if kw in col.lower():
                return col
    return None


# ── Data loaders (cached forever until file changes) ─────────────────────────

@st.cache_data(show_spinner=False)
def load_zone_risk() -> pd.DataFrame:
    path = ARTIFACTS / "zone_risk.parquet"
    df = pd.read_parquet(path)

    lat_col  = find_col(df, "lat")
    lon_col  = find_col(df, "lon", "lng")
    risk_col = find_col(df, "risk", "score", "pcis")
    name_col = find_col(df, "name", "location", "zone", "junction")

    if not lat_col or not lon_col:
        return pd.DataFrame(columns=["lat", "lon", "risk", "name"])

    result = pd.DataFrame()
    result["lat"]  = pd.to_numeric(df[lat_col],  errors="coerce")
    result["lon"]  = pd.to_numeric(df[lon_col],  errors="coerce")
    result["risk"] = pd.to_numeric(df[risk_col], errors="coerce").fillna(0) if risk_col else 0
    result["name"] = df[name_col].values if name_col else "Unknown Zone"

    return result.dropna(subset=["lat", "lon"]).reset_index(drop=True)


@st.cache_data(show_spinner=False)
def load_violations() -> pd.DataFrame:
    path = ARTIFACTS / "violations_scored.parquet"
    df = pd.read_parquet(path)

    lat_col     = find_col(df, "lat")
    lon_col     = find_col(df, "lon", "lng")
    vehicle_col = find_col(df, "vehicle", "plate", "registration")

    if not lat_col or not lon_col:
        return pd.DataFrame(columns=["lat", "lon", "vehicle"])

    result = pd.DataFrame()
    result["lat"]     = pd.to_numeric(df[lat_col], errors="coerce")
    result["lon"]     = pd.to_numeric(df[lon_col], errors="coerce")
    result["vehicle"] = df[vehicle_col].values if vehicle_col else "Unknown"

    return result.dropna(subset=["lat", "lon"]).reset_index(drop=True)


@st.cache_data(show_spinner=False)
def load_repeat_offenders() -> pd.DataFrame:
    violations = load_violations()
    if "vehicle" not in violations.columns:
        return pd.DataFrame(columns=["vehicle", "count", "lat", "lon"])

    counts = (
        violations.groupby("vehicle", dropna=False)
        .size()
        .reset_index(name="count")
        .sort_values(["count", "vehicle"], ascending=[False, True])
    )
    repeat = counts[counts["count"] >= 3].head(50)

    if repeat.empty:
        return repeat

    vehicle_coords = (
        violations.groupby("vehicle", dropna=False)
        .agg(lat=("lat", "mean"), lon=("lon", "mean"))
        .reset_index()
    )
    return repeat.merge(vehicle_coords, on="vehicle", how="left")


# ── Map builders (cached by layer key + dataframe hash) ──────────────────────
# Wrapping build functions with @st.cache_data means the folium HTML is only
# regenerated when the underlying data actually changes — not on every widget
# interaction. We pass primitive arguments so Streamlit can hash them cheaply.

@st.cache_data(show_spinner=False)
def _cached_heatmap(df_zones: pd.DataFrame) -> str:
    m = _base_map()
    heat_data = df_zones[["lat", "lon", "risk"]].dropna().values.tolist()
    HeatMap(
        heat_data,
        name="Violation Heatmap",
        min_opacity=0.4,
        max_zoom=16,
        radius=28,
        blur=18,
        gradient={0.2: "blue", 0.45: "lime", 0.65: "yellow", 0.85: "orange", 1.0: "red"},
    ).add_to(m)
    for _, row in df_zones.nlargest(5, "risk").iterrows():
        folium.Marker(
            location=[row["lat"], row["lon"]],
            icon=folium.DivIcon(
                html=(
                    f'<div style="background:#E53E3E;color:#fff;padding:3px 7px;'
                    f'border-radius:10px;font-size:11px;font-weight:600;white-space:nowrap;">'
                    f'{row.get("name", "Hotspot")}</div>'
                ),
                icon_size=(140, 24),
            ),
        ).add_to(m)
    return m


@st.cache_data(show_spinner=False)
def _cached_deployment(df_zones: pd.DataFrame) -> folium.Map:
    m = _base_map()
    top = df_zones.sort_values("risk", ascending=False).reset_index(drop=True)
    for i, row in top.iterrows():
        risk = float(row.get("risk", 0) or 0)
        name = row.get("name", f"Zone {i + 1}")
        if i < 3:
            color, priority = "#ef4444", "HIGH"
        elif i < 7:
            color, priority = "#f97316", "MED"
        else:
            color, priority = "#eab308", "LOW"
        radius = max(8, int(risk * 3))
        popup = folium.Popup(
            f"<b>{name}</b><br>Risk score: {risk:.1f}<br>Priority: {priority}<br>"
            f"Recommended officers: {max(1, int(risk / 3))}",
            max_width=220,
        )
        folium.CircleMarker(
            location=[row["lat"], row["lon"]],
            radius=radius, color=color, fill=True,
            fill_color=color, fill_opacity=0.42,
            popup=popup, tooltip=f"{name} ({priority})",
        ).add_to(m)
        folium.Marker(
            location=[row["lat"], row["lon"]],
            icon=folium.DivIcon(
                html=(
                    f'<div style="background:{color};color:#fff;width:22px;height:22px;'
                    f'border-radius:50%;text-align:center;line-height:22px;'
                    f'font-weight:700;font-size:12px;border:2px solid #fff">{i + 1}</div>'
                ),
                icon_size=(22, 22), icon_anchor=(11, 11),
            ),
        ).add_to(m)
    return m


@st.cache_data(show_spinner=False)
def _cached_traffic(df_zones: pd.DataFrame) -> folium.Map:
    m = _base_map()
    top = df_zones.sort_values("risk", ascending=False).head(8).reset_index(drop=True)
    for _, row in top.iterrows():
        risk = float(row.get("risk", 0) or 0)
        folium.Circle(
            location=[row["lat"], row["lon"]], radius=int(risk * 130),
            color="#ef4444", fill=True, fill_color="#ef4444",
            fill_opacity=0.08, weight=1, tooltip=row.get("name", "Hotspot"),
        ).add_to(m)
        folium.CircleMarker(
            location=[row["lat"], row["lon"]], radius=6,
            color="#ef4444", fill=True, fill_color="#ef4444",
            fill_opacity=0.9, tooltip=row.get("name", "Hotspot"),
        ).add_to(m)
    for route in [
        [[12.9358, 77.6149], [12.9176, 77.6228], [12.8977, 77.6374]],
        [[12.9249, 77.5538], [12.8936, 77.5718], [12.8617, 77.5890]],
        [[13.0219, 77.5543], [13.0358, 77.5970], [13.0610, 77.5933]],
    ]:
        AntPath(locations=route, color="#22c55e", weight=4, opacity=0.75,
                delay=800, tooltip="Alternate route").add_to(m)
    m.get_root().html.add_child(folium.Element("""
    <div style='position:fixed;bottom:30px;left:30px;z-index:999;background:white;
         padding:10px 16px;border-radius:8px;border:1px solid #ddd;font-size:12px'>
      <b>Traffic Guide</b><br>
      <span style='color:#ef4444'>●</span> Obstruction zone<br>
      <span style='color:#22c55e'>→</span> Alternate route
    </div>"""))
    return m


@st.cache_data(show_spinner=False)
def _cached_patrol(df_zones: pd.DataFrame) -> folium.Map:
    m = _base_map()
    top = df_zones.sort_values("risk", ascending=False).head(12).reset_index(drop=True)
    beats = {
        "Beat A (North)":   {"color": "#3182ce", "mask": top["lat"] > 13.00},
        "Beat B (Central)": {"color": "#8b5cf6", "mask": (top["lat"] >= 12.93) & (top["lat"] <= 13.00)},
        "Beat C (South)":   {"color": "#f59e0b", "mask": top["lat"] < 12.93},
    }
    for beat_name, info in beats.items():
        zones = top[info["mask"]].reset_index(drop=True)
        if zones.empty:
            continue
        coords = zones[["lat", "lon"]].values.tolist()
        if len(coords) >= 2:
            AntPath(locations=coords, color=info["color"], weight=3,
                    opacity=0.8, delay=700, tooltip=beat_name).add_to(m)
        for _, row in zones.iterrows():
            folium.CircleMarker(
                location=[row["lat"], row["lon"]], radius=8,
                color=info["color"], fill=True, fill_color=info["color"],
                fill_opacity=0.7, tooltip=f"{beat_name}: {row.get('name', 'Zone')}",
            ).add_to(m)
    m.get_root().html.add_child(folium.Element("""
    <div style='position:fixed;bottom:30px;left:30px;z-index:999;background:white;
         padding:10px 16px;border-radius:8px;border:1px solid #ddd;font-size:12px'>
      <b>Patrol Beats</b><br>
      <span style='color:#3182ce'>●</span> Beat A (North)<br>
      <span style='color:#8b5cf6'>●</span> Beat B (Central)<br>
      <span style='color:#f59e0b'>●</span> Beat C (South)
    </div>"""))
    return m


@st.cache_data(show_spinner=False)
def _cached_offenders(df_repeat: pd.DataFrame) -> folium.Map:
    m = _base_map()
    cluster = MarkerCluster(name="Repeat Offenders").add_to(m)
    for _, row in df_repeat.iterrows():
        count = int(row.get("count", 0) or 0)
        if count >= 8:
            color, label = "#ef4444", "PRIORITY TARGET"
        elif count >= 5:
            color, label = "#f97316", "Monitor"
        else:
            color, label = "#eab308", "Watch"
        folium.CircleMarker(
            location=[row["lat"], row["lon"]],
            radius=min(18, 6 + count), color=color,
            fill=True, fill_color=color, fill_opacity=0.65,
            tooltip=f"{row['vehicle']} — {count} violations",
            popup=folium.Popup(
                f"<b>{row['vehicle']}</b><br>Violations: {count}<br>{label}",
                max_width=180,
            ),
        ).add_to(cluster)
    return m


def _base_map() -> folium.Map:
    return folium.Map(
        location=[BLR_LAT, BLR_LON],
        zoom_start=12,
        tiles="CartoDB positron",
        control_scale=True,
    )


# ── Page layout ───────────────────────────────────────────────────────────────

zone_df   = load_zone_risk()
viol_df   = load_violations()
repeat_df = load_repeat_offenders()

layer_options = {
    "🔥 Violation Heatmap":     "heatmap",
    "🚔 Patrol Deployment":     "deployment",
    "🚦 Traffic Avoidance":     "traffic",
    "🛣 Patrol Routes (Beats)": "patrol",
    "🔁 Repeat Offenders":      "offenders",
}
layer_descriptions = {
    "heatmap":    "Shows violation concentration across the city. Use this for a quick read on chronic problem areas.",
    "deployment": "Ranks zones by priority so the best deployment order is obvious.",
    "traffic":    "Highlights obstruction-prone areas and suggests alternate delivery routes.",
    "patrol":     "Shows ready-to-share patrol beats for shift officers.",
    "offenders":  "Clusters repeat-offending vehicles by their most frequent operating zone.",
}

# Top metrics
st.markdown("### Insights")
c1, c2, c3, c4 = st.columns(4)
c1.metric("Total violations",  f"{len(viol_df):,}")
c2.metric("High-risk zones",   f"{int((zone_df['risk'] >= 7).sum())}")
c3.metric("Repeat offenders",  f"{len(repeat_df)}")
c4.metric("Locations tracked", f"{len(zone_df)}")

st.divider()

map_col, control_col = st.columns([2.2, 1])

with control_col:
    st.markdown("### Filters & controls")
    selected_label = st.radio(
        "Map layer",
        options=list(layer_options.keys()),
        index=0,
        label_visibility="collapsed",
    )
    st.markdown(
        f'<div style="background:#0f172a;border-left:4px solid #3b82f6;padding:10px 14px;'
        f'border-radius:6px;color:#e2e8f0;margin-bottom:12px;">'
        f'ℹ️ {layer_descriptions[layer_options[selected_label]]}</div>',
        unsafe_allow_html=True,
    )
    with st.expander("⏰ Time of day filter", expanded=True):
        time_slot = st.selectbox(
            "Shift window",
            options=["Morning", "Afternoon", "Evening", "Night"],
        )
        st.caption(
            f"Current view: **{time_slot}**. The map title and text update for "
            f"presentation, while the data remains the same."
        )
    st.info(
        "Need a quick recommendation? Open the Situation Room and ask: "
        "'Where should I deploy 3 officers tonight for max impact?'"
    )

with map_col:
    st.markdown(
        f'<div style="font-size:1.1rem;font-weight:700;margin:0.5rem 0;">'
        f'{time_slot} view · {selected_label}</div>',
        unsafe_allow_html=True,
    )

    key = layer_options[selected_label]

    # Build (or retrieve from cache) the folium map
    if key == "heatmap":
        m = _cached_heatmap(zone_df)
    elif key == "deployment":
        m = _cached_deployment(zone_df)
    elif key == "traffic":
        m = _cached_traffic(zone_df)
    elif key == "patrol":
        m = _cached_patrol(zone_df)
    else:
        m = _cached_offenders(repeat_df)

    folium.LayerControl().add_to(m)

    # key= prevents st_folium re-initialising the map on every widget change
    st_folium(m, width="100%", height=620, returned_objects=[], key=f"map_{key}")