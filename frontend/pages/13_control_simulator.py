import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import folium
import streamlit as st
from streamlit_folium import st_folium

from frontend.utils.api_client import simulate_control
from frontend.utils.ui import apply_brand, page_header

apply_brand()

page_header("Control Simulator - Tactical Layers", "Simulate the 5 operational traffic control layers in real-time.")

with st.expander("About the 5 Tactical Layers", expanded=False):
    st.markdown("""
0. **Validation Gatekeeper** - Check historical approval rate. If < 60%, block all tactical actions.
1. **Anti-Gridlock Hold** - If violation within 50m of junction, hold conflicting green phase for 5s.
2. **Heavy Discharge Extension** - If TANKER/PASSENGER blocks lane, add +7s green for 3 cycles.
3. **Shockwave Dampening (VMS)** - Drop upstream VMS speed to 30 km/h for 5 min.
4. **Zipper-Merge Cone Map** - Generate GPS coordinates for a 7-degree cone taper.
    """)

st.markdown("---")
st.subheader("Simulate Blockage")

c1, c2, c3 = st.columns(3)
with c1:
    lat = st.number_input("Latitude", value=12.9716, format="%.6f", step=0.001)
with c2:
    lon = st.number_input("Longitude", value=77.5946, format="%.6f", step=0.001)
with c3:
    vehicle_type = st.selectbox("Vehicle Type", ["CAR", "SCOOTER", "TANKER", "BUS", "TRUCK", "PASSENGER AUTO", "LGV", "LCV", "MOTOR CYCLE"])

if st.button("Simulate Blockage", type="primary", use_container_width=True):
    with st.spinner("Executing tactical layers..."):
        result = simulate_control(lat, lon, vehicle_type)

    if result.get("error"):
        st.error(result["error"])
    else:
        step_colors = {"PASSED": "#22c55e", "EXECUTED": "#3b82f6", "SKIPPED": "#94a3b8", "BLOCKED": "#ef4444", "DISPLAYED": "#8b5cf6"}
        st.success(f"Simulation complete - {result['total_layers']} layers executed")
        
        st.markdown("### Execution Steps")
        for step in result["steps"]:
            color = step_colors.get(step["status"], "#94a3b8")
            st.markdown(
                f"<div style='background:#111318;border:1px solid #1C2030;border-left:4px solid {color};"
                f"border-radius:4px;padding:12px 16px;margin:8px 0;'>"
                f"<b>Layer {step['layer']}: {step['name']}</b> "
                f"<span style='color:{color};font-weight:600;'>[{step['status']}]</span><br>"
                f"<span style='color:#94a3b8;font-size:12px;'>{step['detail']}</span></div>",
                unsafe_allow_html=True)

        st.markdown("---")
        st.markdown("### Visual Map Overlay")
        m = folium.Map(location=[lat, lon], zoom_start=16, tiles="CartoDB dark_matter")
        folium.Marker([lat, lon], popup=f"Blockage: {vehicle_type}", icon=folium.Icon(color="red", icon="info-sign")).add_to(m)
        for step in result["steps"]:
            if "cone_coordinates" in step:
                for pt in step["cone_coordinates"]:
                    folium.CircleMarker([pt["lat"], pt["lon"]], radius=3, color="#8b5cf6", fill=True, fill_opacity=0.7).add_to(m)
        st_folium(m, width=None, height=400, returned_objects=[])

        with st.expander("Action Log Timeline"):
            st.markdown(f"**Timestamp:** {result['timestamp']}")
            st.markdown(f"**Location:** {lat}, {lon} ({result.get('risk_tier', 'Unknown')})")
            st.markdown(f"**Vehicle:** {vehicle_type}")
            for step in result["steps"]:
                st.markdown(f"At {result['timestamp'][:19]}: Layer {step['layer']} triggered - {step['status']}")
        
        st.info(f"Confidence score: {result['confidence']:.0%} - "
                f"{'All actions cleared' if not result.get('validation_blocked') else 'Some actions blocked by Gatekeeper'}")
else:
    st.info("Enter coordinates and vehicle type, then click 'Simulate Blockage'")
