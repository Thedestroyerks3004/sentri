import folium
import plotly.graph_objects as go
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from utils.api_client import get_repeat_offenders, get_vehicle
from utils.ui import page_header, wow_moment

page_header("🔁 Repeat Offenders", "3,489 vehicles with 5+ violations — zero institutional memory.")

data = get_repeat_offenders()
top50 = pd.DataFrame(data["top50"])
dist = pd.DataFrame(data["distribution"])

st.metric("Vehicles with 5+ violations", f"{data['repeat_5plus']:,}")
wow_moment(
    f"Top offender: <b>{data['top_vehicle']}</b> — <b>{data['max_violations']}</b> violations, still on the road."
)

search = st.text_input("Search vehicle number", placeholder="e.g. FKN00GL4424")
if search:
    result = get_vehicle(search)
    if result["count"] == 0:
        st.warning("No violations found.")
    else:
        st.success(f"Found {result['count']} violations for **{result['vehicle_number']}**")
        hist = pd.DataFrame(result["violations"])
        m = folium.Map(
            location=[hist["latitude"].mean(), hist["longitude"].mean()],
            zoom_start=13, tiles="CartoDB dark_matter",
        )
        for _, row in hist.iterrows():
            folium.CircleMarker(
                location=[row["latitude"], row["longitude"]], radius=6, color="#ef4444", fill=True,
                popup=f"{row['violation_type_parsed']} — {row['police_station']}",
            ).add_to(m)
        st_folium(m, width=None, height=380, returned_objects=[])
        st.dataframe(hist, use_container_width=True, hide_index=True)

st.subheader("Top 50 repeat offenders")
st.dataframe(top50, use_container_width=True, hide_index=True, height=360)

fig = go.Figure(go.Bar(x=dist["bucket"], y=dist["vehicles"], marker_color="#3b82f6"))
fig.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", height=320)
st.plotly_chart(fig, use_container_width=True)
