import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import folium
import streamlit as st
from streamlit_folium import st_folium

from frontend.utils.api_client import get_junctions, simulate_control
from frontend.utils.ui import apply_brand, page_header

apply_brand()

page_header(
    "🎮 Control Simulator - Tactical Layers",
    "Simulate a traffic blockage at any Bengaluru junction and watch how the 5-layer tactical response system reacts in real time.",
)

# ── Initialize session state for location persistence ────────────────────
if "sim_lat" not in st.session_state:
    st.session_state.sim_lat = 12.9716
if "sim_lon" not in st.session_state:
    st.session_state.sim_lon = 77.5946
if "sim_location_name" not in st.session_state:
    st.session_state.sim_location_name = ""


# ── Preset Bengaluru junctions (fallback if API is unreachable) ──────────────
PRESET_JUNCTIONS = {
    "Safina Plaza Junction (BTP051)": (12.9716, 77.5946),
    "KR Market Junction (BTP082)": (12.9637, 77.5760),
    "Elite Junction (BTP040)": (12.9770, 77.5710),
    "Sagar Theatre Junction (BTP044)": (12.9820, 77.5800),
    "Central Street Junction (BTP211)": (12.9750, 77.5900),
    "M.G. Road Junction": (12.9756, 77.6066),
    "Commercial Street": (12.9822, 77.6033),
    "Majestic Bus Stand": (12.9767, 77.5713),
    "Silk Board Junction": (12.9182, 77.6228),
    "Marathahalli Bridge": (12.9565, 77.7012),
    "Hebbal Flyover": (13.0358, 77.5970),
    "Yeshwanthpur Circle": (13.0227, 77.5467),
    "Koramangala Sony World": (12.9352, 77.6245),
    "Whitefield Main Road": (12.9698, 77.7500),
    "Electronic City Toll": (12.8399, 77.6770),
}

# ── Build sorted junction list (highest violations first) ────────────────
live_junctions = []
try:
    api_junctions = get_junctions(limit=30)
    if isinstance(api_junctions, list) and len(api_junctions) > 0:
        for j in api_junctions:
            name = j.get("junction_name_clean", "")
            lat = j.get("latitude")
            lon = j.get("longitude")
            if name and lat and lon and name != "No Junction":
                violations = j.get("violation_count", 0)
                live_junctions.append((name, float(lat), float(lon), int(violations)))
except Exception:
    pass

# Combine: API results (with violation counts) + presets (0 violations)
all_junctions = []
seen_names = set()
for name, lat, lon, count in sorted(live_junctions, key=lambda x: x[3], reverse=True):
    label = f"{name}"
    all_junctions.append((label, lat, lon, count))
    seen_names.add(name.lower())

for pname, (plat, plon) in PRESET_JUNCTIONS.items():
    short = pname.split(" (")[0]
    if short.lower() not in seen_names:
        all_junctions.append((pname, plat, plon, 0))

junction_map = {label: (lat, lon) for label, lat, lon, _ in all_junctions}


# ============================================================================
# LAYOUT — Step-by-step wizard
# ============================================================================

with st.expander("How the 5 Tactical Layers Work", expanded=False):
    st.markdown("""
| Layer | Name | What It Does |
|-------|------|-------------|
| 0 | **Validation Gatekeeper** 🛡️ | Checks if this location has a history of valid violations. If approval rate is too low (<30%), blocks all actions. |
| 1 | **Anti-Gridlock Hold** 🚦 | If blockage is within 50m of a junction, holds the conflicting green phase for 5 seconds. |
| 2 | **Heavy Discharge Extension** 🟢 | If a TANKER, BUS, or TRUCK is blocking the lane, adds +7s green for 3 cycles. |
| 3 | **Shockwave Dampening (VMS)** 🪧 | Drops upstream VMS speed signs to 30 km/h for 5 minutes to slow approaching traffic. |
| 4 | **Zipper-Merge Cone Map** 📐 | Generates GPS coordinates for a 7° cone taper — ready for the beat constable. |
    """)

st.markdown("---")

## Configure Simulation

# ── Location + Vehicle in one row ─────────────────────────────────────────
col_loc, col_veh = st.columns([3, 1])

with col_loc:
    junction_labels = [f"{n} ({c:,} violations)" if c > 0 else n for n, _, _, c in all_junctions]
    selected_junction = st.selectbox(
        "Location",
        options=[""] + junction_labels,
        label_visibility="collapsed",
    )
    
    with st.expander("Or enter custom coordinates", expanded=False):
        cc1, cc2 = st.columns(2)
        with cc1:
            custom_lat = st.number_input("Lat", value=12.9716, format="%.6f", step=0.001)
        with cc2:
            custom_lon = st.number_input("Lon", value=77.5946, format="%.6f", step=0.001)
        if st.button("Apply coordinates", use_container_width=True, type="secondary"):
            st.session_state.sim_lat = custom_lat
            st.session_state.sim_lon = custom_lon
            st.session_state.sim_location_name = f"{custom_lat:.4f}, {custom_lon:.4f}"

with col_veh:
    vehicle_type = st.selectbox(
        "Vehicle",
        ["CAR", "SCOOTER", "TANKER", "BUS", "TRUCK", "PASSENGER AUTO", "LGV", "LCV", "MOTOR CYCLE"],
        index=0,
    )
    
    heavy_vehicles = ["TANKER", "TRUCK", "BUS", "LCV", "LGV"]
    if vehicle_type in heavy_vehicles:
        st.caption("Triggers Layer 2")
    else:
        st.caption("Layer 2 skipped")

st.markdown("#### Quick select")

# ── Preset buttons ───────────────────────────────────────────────────────────
preset_keys = list(PRESET_JUNCTIONS.keys())[:6]
preset_cols = st.columns(6)
for i, name in enumerate(preset_keys):
    with preset_cols[i]:
        short = name.split("(")[0].strip()
        p_lat, p_lon = PRESET_JUNCTIONS[name]
        if st.button(short.split("Junction")[0].strip() if "Junction" in short else short, use_container_width=True, key=f"preset_{i}"):
            st.session_state.sim_lat = p_lat
            st.session_state.sim_lon = p_lon
            st.session_state.sim_location_name = name

# ── Resolve selected location ─────────────────────────────────────────────
if selected_junction:
    raw_name = selected_junction.rsplit(" (", 1)[0] if " violations" in selected_junction else selected_junction
    for label, slat, slon, _ in all_junctions:
        if label == raw_name or label.startswith(raw_name):
            st.session_state.sim_lat = slat
            st.session_state.sim_lon = slon
            st.session_state.sim_location_name = selected_junction
            break

lat = st.session_state.sim_lat
lon = st.session_state.sim_lon
location_label = st.session_state.sim_location_name if st.session_state.sim_location_name else f"{lat:.4f}, {lon:.4f}"

st.markdown("---")

## Run

# ── Run button ───────────────────────────────────────────────────────────────
run_col1, run_col2 = st.columns([2, 1])
with run_col1:
    simulate_clicked = st.button("Simulate", type="primary", use_container_width=True)
with run_col2:
    st.caption(f"{location_label}")

if simulate_clicked:
    with st.spinner(f"Executing 5 tactical layers at {location_label}..."):
        result = simulate_control(lat, lon, vehicle_type)

    if result.get("error"):
        st.error(f"Simulation failed: {result['error']}")
    else:
        # ── Results header ──────────────────────────────────────────────────
        total = result["total_layers"]
        passed = sum(1 for s in result["steps"] if s["status"] in ("PASSED", "EXECUTED", "DISPLAYED"))
        blocked = sum(1 for s in result["steps"] if s["status"] == "BLOCKED")

        st.success(f"Simulation complete — {passed}/{total} layers executed at {location_label}")

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Confidence", f"{result['confidence']:.0%}")
        m2.metric("Risk Tier", result.get("risk_tier", "Unknown"))
        m3.metric("Layers", f"{passed}/{total}")
        m4.metric("Vehicle", result["vehicle_type"])

        st.markdown("---")

        st.markdown("## Execution Timeline")

        step_colors = {
            "PASSED": "#22c55e", "EXECUTED": "#3b82f6",
            "SKIPPED": "#64748b", "BLOCKED": "#ef4444", "DISPLAYED": "#8b5cf6",
        }
        step_bg = {
            "PASSED": "#0a2e1a", "EXECUTED": "#0a1e3a",
            "SKIPPED": "#1a1a2a", "BLOCKED": "#2a0e0e", "DISPLAYED": "#1a0a3a",
        }

        for step in result["steps"]:
            status = step["status"]
            color = step_colors.get(status, "#94a3b8")
            bg = step_bg.get(status, "#111318")

            st.markdown(
                f"<div style='background:{bg};border:1px solid #1C2030;border-left:4px solid {color};"
                f"border-radius:8px;padding:14px 18px;margin:10px 0;'>"
                f"<div style='display:flex;justify-content:space-between;align-items:center;'>"
                f"<span style='font-size:14px;font-weight:600;'>Layer {step['layer']}: {step['name']}</span>"
                f"<span style='color:{color};font-weight:700;font-size:13px;'>{status}</span>"
                f"</div>"
                f"<div style='color:#94a3b8;font-size:13px;margin-top:6px;'>{step['detail']}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )

        st.markdown("---")
        st.markdown("## Map")

        m = folium.Map(location=[lat, lon], zoom_start=16, tiles="CartoDB dark_matter")

        folium.Marker(
            [lat, lon],
            popup=f"{vehicle_type} blockage",
            icon=folium.Icon(color="red", icon="info-sign"),
        ).add_to(m)

        for step in result["steps"]:
            if "cone_coordinates" in step:
                for pt in step["cone_coordinates"]:
                    folium.CircleMarker(
                        [pt["lat"], pt["lon"]],
                        radius=4, color="#8b5cf6", fill=True, fill_opacity=0.8,
                    ).add_to(m)
                pts = [(c["lat"], c["lon"]) for c in step["cone_coordinates"]]
                if pts:
                    folium.PolyLine(pts, color="#8b5cf6", weight=2, opacity=0.5, dash_array="4").add_to(m)

        st_folium(m, width=None, height=500, returned_objects=[])

        st.markdown("---")
        if result.get("validation_blocked"):
            st.error("Gatekeeper blocked — approval rate too low for this area.")
        else:
            st.success("Gatekeeper cleared — all tactical actions executed.")

else:
    st.info("Select a location and vehicle type above, then click Simulate Blockage.")
