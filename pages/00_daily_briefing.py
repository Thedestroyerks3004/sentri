import os

import pandas as pd
import requests
import streamlit as st

API_BASE = os.getenv("SENTRI_API_URL", "http://127.0.0.1:8000").rstrip("/")

from utils.api_client import api_available, get_daily_briefing
from utils.pdf_briefing import generate_briefing_pdf
from utils.ui import apply_brand, format_indian

apply_brand()

if not api_available():
    st.error(
        "The API is not ready or is running an outdated build. "
        "Restart the backend with `python run_api.py` and reload this page."
    )
    st.stop()

try:
    briefing = get_daily_briefing()
except Exception as exc:
    st.error(
        "The daily briefing endpoint could not be loaded. "
        "Please restart the API server and refresh the page."
    )
    st.caption(str(exc))
    st.stop()

snap = briefing["snapshot"]

hc1, hc2, hc3 = st.columns([2, 3, 2])
with hc1:
    st.markdown("###  **SENTRI**")
    st.caption("Parking Intelligence")
with hc2:
    st.markdown(
        "<p style='text-align:center;font-size:1.4rem;font-weight:800;letter-spacing:0.08em;"
        "margin:0;'>DAILY ENFORCEMENT BRIEFING</p>",
        unsafe_allow_html=True,
    )
with hc3:
    st.markdown(f"<p style='text-align:right;margin:0;'>{briefing['generated_at']}</p>", unsafe_allow_html=True)

risk = briefing["city_risk_level"]
risk_color = briefing["city_risk_color"]
st.markdown(
    f"<div class='risk-banner' style='background:{risk_color}22;border:2px solid {risk_color};"
    f"color:{risk_color};'>TODAY'S CITY RISK LEVEL: {risk}</div>",
    unsafe_allow_html=True,
)

st.markdown("---")
st.subheader("City Snapshot")
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Predicted violations today", format_indian(snap["predicted_today"]))
c2.metric("Active hotspots (this hour)", format_indian(snap["active_hotspots_now"]))
c3.metric("Repeat offenders flagged (week)", format_indian(snap["repeat_offenders_week"]))
c4.metric("Integrity alerts (week)", format_indian(snap["integrity_alerts_week"]))
c5.metric("Live spikes (4h)", format_indian(snap["live_spikes_4h"]))
st.caption(f"Data freshness: {snap['freshness']}")

st.markdown("---")
st.subheader("Top 5 Patrol Zones Today")
patrol_df = pd.DataFrame(briefing["patrol_zones"])
if not patrol_df.empty:
    st.dataframe(
        patrol_df.rename(columns={
            "rank": "Rank", "zone": "Zone", "risk": "Risk",
            "peak_window": "Peak Window", "predicted_today": "Predicted Today",
            "station": "Station", "action": "Action",
        }),
        use_container_width=True,
        hide_index=True,
    )

st.markdown("---")
st.markdown(
    "<div style='border:2px solid #ef4444;border-radius:8px;padding:1rem;'>"
    "<h4 style='color:#ef4444;margin-top:0;'>⚠️ AI-Flagged Enforcement Anomalies This Period</h4>",
    unsafe_allow_html=True,
)
if briefing["integrity_alerts"]:
    st.dataframe(
        pd.DataFrame(briefing["integrity_alerts"]).rename(columns={
            "officer_id": "Officer ID", "station": "Station",
            "anomaly_type": "Anomaly Type", "severity": "Severity Score",
            "flagged_on": "Flagged On",
        }),
        use_container_width=True,
        hide_index=True,
    )
st.caption(
    f"These records have been automatically flagged for internal review. "
    f"Total flagged this period: **{briefing['integrity_total']:,}** records."
)
st.markdown("</div>", unsafe_allow_html=True)

st.markdown("---")
st.subheader("Repeat Offenders Active This Week")
repeat_df = pd.DataFrame(briefing["repeat_offenders_active"])
if not repeat_df.empty:
    st.dataframe(
        repeat_df.rename(columns={
            "vehicle_number": "Vehicle Number", "vehicle_type": "Type",
            "violations": "Violations This Week", "last_zone": "Last Seen Zone",
            "stations": "Stations Involved",
        }),
        use_container_width=True,
        hide_index=True,
    )
st.caption(
    "These vehicles have shown persistent violation behaviour. "
    "Recommend escalation to RTO for license review."
)

st.markdown("---")
st.subheader("Station Performance Snapshot")
stations_df = pd.DataFrame(briefing["station_performance"])
if not stations_df.empty:
    display = stations_df[["police_station", "filed", "approved", "rejected", "rejection_rate", "trend"]].copy()
    display.columns = ["Station", "Filed This Week", "Approved", "Rejected", "Rejection Rate", "Trend"]
    display["Rejection Rate"] = display["Rejection Rate"].round(1).astype(str) + "%"
    st.dataframe(display, use_container_width=True, hide_index=True)

st.markdown("---")
st.subheader("🚨 Dispatch Actions")

twilio_vars = {
    "TWILIO_ACCOUNT_SID": os.getenv("TWILIO_ACCOUNT_SID"),
    "TWILIO_AUTH_TOKEN": os.getenv("TWILIO_AUTH_TOKEN"),
    "TWILIO_PHONE_NUMBER": os.getenv("TWILIO_PHONE_NUMBER"),
    "TWILIO_TO_NUMBER": os.getenv("TWILIO_TO_NUMBER"),
}
twilio_ready = all(twilio_vars[name] for name in ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_PHONE_NUMBER"))
missing_twilio = [name for name, value in twilio_vars.items() if not value]

if twilio_ready:
    st.success(
        "SMS dispatch is configured and ready to send messages."
    )
else:
    st.warning(
        "SMS dispatch is disabled because one or more Twilio credentials are missing. "
        f"Missing values: {', '.join(missing_twilio) if missing_twilio else 'none'}."
    )

col1, col2 = st.columns([1, 3])
with col1:
    if st.button("Run Dispatch Now", use_container_width=True, disabled=not twilio_ready):
        try:
            response = requests.post(f"{API_BASE}/api/dispatch/run", timeout=120)
            response.raise_for_status()
            result = response.json()
            if result.get("error"):
                st.error(f"Dispatch failed: {result['error']}")
            else:
                dispatched = result.get("dispatched", 0)
                succeeded = result.get("succeeded", 0)
                if succeeded == 0:
                    st.warning(
                        f"Dispatched {dispatched} officer(s); {succeeded} succeeded."
                    )
                    failure_details = result.get("failure_details") or []
                    if failure_details:
                        for detail in failure_details:
                            st.caption(f"• {detail}")
                else:
                    st.success(
                        f"Dispatched {dispatched} officer(s); {succeeded} succeeded."
                    )
        except Exception as exc:
            st.error(f"Dispatch request failed: {exc}")

st.markdown("---")
st.subheader("Recent Dispatches")
try:
    dispatch_resp = requests.get(f"{API_BASE}/api/dispatch/log", timeout=30)
    dispatch_resp.raise_for_status()
    dispatch_rows = dispatch_resp.json()
    if dispatch_rows:
        dispatch_df = pd.DataFrame(dispatch_rows)
        dispatch_df = dispatch_df.rename(columns={
            "timestamp": "Time",
            "officer_id": "Officer",
            "zone_name": "Zone",
            "risk_tier": "Risk",
            "predicted_violations": "Predicted",
            "distance_km": "Distance",
            "sms_status": "Status",
            "error_detail": "Error Detail",
            "recipient_phone": "Recipient",
        })
        success_count = int((dispatch_df["Status"].astype(str).str.lower().str.contains("delivered|sent|success", regex=True)).sum())
        total_count = len(dispatch_df)
        success_rate = round(success_count / total_count * 100, 1) if total_count else 0.0
        c1, c2, c3 = st.columns([1, 1, 2])
        c1.metric("Dispatch attempts", total_count)
        c2.metric("Successful sends", success_count)
        c3.metric("Success rate", f"{success_rate:.1f}%")
        st.dataframe(dispatch_df, use_container_width=True, hide_index=True)
        if st.button("Acknowledge latest delivered dispatch", use_container_width=True):
            try:
                ack_resp = requests.post(f"{API_BASE}/api/dispatch/acknowledge", timeout=30)
                ack_resp.raise_for_status()
                ack_data = ack_resp.json()
                if ack_data.get("acknowledged"):
                    st.success(
                        f"Acknowledged dispatch #{ack_data.get('index')} at {ack_data.get('acknowledged_at')}"
                    )
                else:
                    st.warning(ack_data.get("error", "Acknowledgement request failed."))
            except Exception as exc:
                st.error(f"Acknowledgement request failed: {exc}")
        st.caption(f"Detailed debug log: {os.path.basename('dispatch_debug.log')}")
    else:
        st.info("No dispatches logged yet.")
except Exception as exc:
    st.caption(f"Unable to load recent dispatches: {exc}")

st.markdown("---")
fc1, fc2 = st.columns([3, 1])
with fc1:
    st.caption("Generated by SENTRI AI — powered by 298,450 violation records")
with fc2:
    pdf_bytes = generate_briefing_pdf(briefing)
    st.download_button(
        label="📄 Export PDF",
        data=pdf_bytes,
        file_name=f"sentri_briefing_{briefing['date']}.pdf",
        mime="application/pdf",
        type="primary",
        use_container_width=True,
    )
