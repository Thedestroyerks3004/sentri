import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import streamlit as st
import pandas as pd

from frontend.utils.api_client import get_citizen_reports
from frontend.utils.ui import apply_brand

apply_brand()

st.markdown("## Bridge of Trust")
st.caption("Citizen Complaint Lifecycle Engine - Track enforcement reports from filing to resolution.")

data = get_citizen_reports()
if data.get("error"):
    st.warning(f"Citizen portal unavailable: {data['error']}")
    st.stop()

reports = data["reports"]
status_counts = data["status_counts"]
escalations = data["escalation_alerts"]
impact = data["my_impact"]

st.markdown("---")
st.markdown("### My Impact")
c1, c2, c3, c4 = st.columns(4)
with c1: st.metric("Total Reports", data["total_reports"])
with c2: st.metric("Resolved", impact["resolved_reports"])
with c3: st.metric("Escalations", len(escalations))
with c4: st.metric("Resolution Rate", f"{round(impact['resolved_reports'] / max(data['total_reports'], 1) * 100, 1)}%")

st.markdown("---")
st.markdown("### Status Overview")
cols = st.columns(len(status_counts))
for i, (status, count) in enumerate(sorted(status_counts.items())):
    with cols[i]: st.metric(status.replace("_", " ").title(), count)

st.markdown("---")
st.markdown("### Escalation Alert Feed")
if escalations:
    st.caption(f"{len(escalations)} reports exceeded the 48-hour review window")
    for e in escalations[:10]:
        st.error(f"{e['tracking_id']} - {e['hours_pending']}h pending - {str(e['violation_type'])[:40]} - {e['police_station']}")
else:
    st.caption("No reports currently exceeding the 48-hour review window.")

st.markdown("---")
st.markdown("### All Reports")
tab, det = st.tabs(["Reports Table", "Report Detail"])

with tab:
    sf = st.multiselect("Filter by status", options=list(status_counts.keys()), default=[], placeholder="All statuses")
    filtered = [r for r in reports if not sf or r["status"] in sf]
    if filtered:
        rows = []
        for r in filtered[:200]:
            rows.append({"Tracking ID": r["tracking_id"], "Status": r["status"].replace("_", " "),
                        "Location": r["location"][:50], "Vehicle": r["vehicle_number"],
                        "Station": r["police_station"], "Pending (h)": r["hours_pending"]})
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        st.caption(f"Showing {len(rows)} of {len(filtered)} reports")
    else:
        st.info("No reports match the current filter.")

with det:
    sid = st.selectbox("Select tracking ID", [r["tracking_id"] for r in reports])
    s = next((r for r in reports if r["tracking_id"] == sid), None)
    if s:
        col1, col2 = st.columns(2)
        with col1:
            st.markdown(f"**Status:** {s['status'].replace('_', ' ')}")
            st.markdown(f"**Location:** {s['location'][:80]}")
            st.markdown(f"**Violation:** {s['violation_type']}")
            st.markdown(f"**Vehicle:** {s['vehicle_number']}")
        with col2:
            st.markdown(f"**Reported:** {s['reported_at'][:19]}")
            st.markdown(f"**Station:** {s['police_station']}")
            if s["hours_pending"] > 0:
                st.markdown(f"**Pending:** {s['hours_pending']}h")
            if s["escalated"]:
                st.error("ESCALATED - Exceeded review window")
        st.markdown("#### State Timeline")
        for t in s["timeline"]:
            st.markdown(f"- {t['status'].replace('_', ' ')} - {t['timestamp'][:19]}")
        if s["auto_closed"]:
            st.info("Auto-closed after 14 days per policy.")
