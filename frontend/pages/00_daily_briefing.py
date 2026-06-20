import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import os

import pandas as pd
import requests
import streamlit as st

API_BASE = os.getenv("SENTRI_API_URL", "http://127.0.0.1:8000").rstrip("/")

from frontend.utils.api_client import api_available, get_daily_briefing
from frontend.utils.pdf_briefing import generate_briefing_pdf
from frontend.utils.ui import apply_brand, format_indian

apply_brand()

if not api_available():
    st.warning(
        "The backend is not reachable yet. Please wait a moment, or click Reload to try again."
    )
    st.caption(f"Current API endpoint: {API_BASE}")
    if st.button("Reload dashboard", use_container_width=True):
        st.rerun()
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
patrol_df = pd.DataFrame(briefing["patrol_zones"])
integrity_df = pd.DataFrame(briefing["integrity_alerts"])
repeat_df = pd.DataFrame(briefing["repeat_offenders_active"])
stations_df = pd.DataFrame(briefing["station_performance"])

# ============================================================================
# HEADER
# ============================================================================
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

# ============================================================================
# HEADLINE: city risk + the single most important number behind it
# ============================================================================
risk = briefing["city_risk_level"]
risk_color = briefing["city_risk_color"]
risk_icon = briefing.get("city_risk_icon", "")
risk_ratio = briefing.get("city_risk_ratio")
ratio_note = f" — {risk_ratio:.2f}× the typical volume for today" if risk_ratio is not None else ""
st.markdown(
    f"<div class='risk-banner' style='background:{risk_color}22;border:2px solid {risk_color};"
    f"color:{risk_color};'>{risk_icon} TODAY'S CITY RISK LEVEL: {risk}{ratio_note}</div>",
    unsafe_allow_html=True,
)

st.markdown("---")
st.subheader("City Snapshot")
c1, c2, c3, c4, c5, c6 = st.columns(6)
c1.metric("Predicted violations today", format_indian(snap["predicted_today"]))
c2.metric("Active hotspots (this hour)", format_indian(snap["active_hotspots_now"]))
c3.metric("Repeat offenders (week)", format_indian(snap["repeat_offenders_week"]))
c4.metric("Integrity alerts (week)", format_indian(snap["integrity_alerts_week"]))
c5.metric("Live spikes (4h)", format_indian(snap["live_spikes_4h"]))
# CHANGED: this was computed by the backend (rejected_count * 15min / 60)
# but never shown anywhere on the page. It's one of the more compelling
# numbers in the whole briefing -- officer-hours lost to rejected/invalid
# filings -- so it belongs in the headline row, not discarded.
c6.metric("Officer-hrs lost (rejections)", format_indian(snap.get("wasted_enforcement_hours", 0)))
st.caption(f"Data freshness: {snap['freshness']}")

# ============================================================================
# SECTION 1: WHAT NEEDS ACTION RIGHT NOW
# Patrol priorities -- this is the operational core of the page, so it
# leads. Dedup bug fixed upstream (was showing the same junction multiple
# times under different internal point IDs).
# ============================================================================
st.markdown("---")
st.subheader("🚓 Top Patrol Priorities — Next 3 Hours")
st.caption("Ranked by predicted violation volume, live activity this hour, and composite risk score.")

if not patrol_df.empty:
    top = patrol_df.iloc[0]
    st.markdown(
        f"<div style='border-left:4px solid {risk_color};padding:0.6rem 1rem;"
        f"background:{risk_color}11;border-radius:6px;margin-bottom:0.75rem;'>"
        f"<b>Highest priority:</b> {top['zone']} ({top.get('top_violation', 'mixed violations')}) — "
        f"{top['predicted_today']} predicted today, patrol window {top['peak_window']}. "
        f"Action: {top['action']}, report to {top['station']}."
        f"</div>",
        unsafe_allow_html=True,
    )

    display_cols = {
        "rank": "Rank", "zone": "Zone", "risk": "Risk",
        "peak_window": "Peak Window", "predicted_today": "Predicted Today",
        "violations_now": "Live (This Hour)", "top_violation": "Top Violation Type",
        "station": "Station", "action": "Action",
    }
    available = [c for c in display_cols if c in patrol_df.columns]
    column_config = {}
    if "predicted_today" in patrol_df.columns:
        column_config["Predicted Today"] = st.column_config.ProgressColumn(
            "Predicted Today", min_value=0,
            max_value=max(int(patrol_df["predicted_today"].max()), 1), format="%d",
        )
    st.dataframe(
        patrol_df[available].rename(columns=display_cols),
        use_container_width=True, hide_index=True,
        column_config=column_config or None,
    )
else:
    st.info("No patrol zone data available for this window.")

# ============================================================================
# SECTION 2: WHAT NEEDS REVIEW
# Integrity alerts + repeat offenders merged into tabs -- both are
# "review, don't act yet" items, and tabbing them avoids two large
# bordered boxes competing for attention on the same page.
# ============================================================================
st.markdown("---")
st.subheader("🔍 Review Queue")

tab_integrity, tab_repeat = st.tabs([
    f"⚠️ Integrity Alerts ({briefing['integrity_total']})",
    f"🔁 Repeat Offenders ({len(repeat_df)})",
])

with tab_integrity:
    if not integrity_df.empty:
        st.dataframe(
            integrity_df.rename(columns={
                "officer_id": "Officer ID", "station": "Station",
                "anomaly_type": "Anomaly Type", "severity": "Severity Score",
                "flagged_on": "Flagged On",
            }),
            use_container_width=True, hide_index=True,
        )
        st.caption(
            "Bulk filing burst = many filings logged in the same second from one officer ID. "
            "Statistical anomaly = filing pattern deviates from that officer's/station's norm. "
            f"Total flagged this period: **{briefing['integrity_total']:,}** records — recommend internal review."
        )
    else:
        st.caption("No anomalies flagged in this period.")

with tab_repeat:
    if not repeat_df.empty:
        st.dataframe(
            repeat_df.rename(columns={
                "vehicle_number": "Vehicle Number", "vehicle_type": "Type",
                "violations": "Violations This Week", "last_zone": "Last Seen Zone",
                "stations": "Stations Involved",
            }),
            use_container_width=True, hide_index=True,
        )
        st.caption(
            "Sorted by violation count this week. Recommend escalation to RTO for license review "
            "on vehicles with 3+ violations across multiple stations."
        )
    else:
        st.caption("No repeat offenders flagged this week.")

# ============================================================================
# SECTION 3: STATION PERFORMANCE
# Add a callout for the worst-performing station instead of a flat table
# the reader has to scan themselves.
# ============================================================================
st.markdown("---")
st.subheader("📊 Station Performance")
if not stations_df.empty:
    worst = stations_df.sort_values("rejection_rate", ascending=False).iloc[0]
    if worst["rejection_rate"] > 0:
        st.caption(
            f"**{worst['police_station']}** has the highest rejection rate this week "
            f"({worst['rejection_rate']:.1f}%, trend {worst['trend']}) — may warrant a filing-quality check-in."
        )
    display = stations_df[["police_station", "filed", "approved", "rejected", "rejection_rate", "trend"]].copy()
    display.columns = ["Station", "Filed This Week", "Approved", "Rejected", "Rejection Rate", "Trend"]
    display["Rejection Rate"] = display["Rejection Rate"].round(1).astype(str) + "%"
    st.dataframe(display, use_container_width=True, hide_index=True)
else:
    st.caption("No station performance data available for this period.")

# ============================================================================
# SECTION 4: DISPATCH (merged "run" + "log" into one section -- they're
# one feature, not two; previously split across two headers/dividers)
# ============================================================================
st.markdown("---")
st.subheader("🚨 Dispatch")

twilio_vars = {
    "TWILIO_ACCOUNT_SID": os.getenv("TWILIO_ACCOUNT_SID"),
    "TWILIO_AUTH_TOKEN": os.getenv("TWILIO_AUTH_TOKEN"),
    "TWILIO_PHONE_NUMBER": os.getenv("TWILIO_PHONE_NUMBER"),
    "TWILIO_TO_NUMBER": os.getenv("TWILIO_TO_NUMBER"),
}
twilio_ready = all(twilio_vars[name] for name in ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_PHONE_NUMBER"))
missing_twilio = [name for name, value in twilio_vars.items() if not value]

dcol1, dcol2 = st.columns([1, 2])
with dcol1:
    if twilio_ready:
        st.success("SMS dispatch is configured.")
    else:
        st.warning(f"SMS dispatch disabled — missing: {', '.join(missing_twilio)}.")
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
                    st.warning(f"Dispatched {dispatched} officer(s); {succeeded} succeeded.")
                    for detail in result.get("failure_details") or []:
                        st.caption(f"• {detail}")
                else:
                    st.success(f"Dispatched {dispatched} officer(s); {succeeded} succeeded.")
        except Exception as exc:
            st.error(f"Dispatch request failed: {exc}")

with dcol2:
    try:
        dispatch_resp = requests.get(f"{API_BASE}/api/dispatch/log", timeout=30)
        dispatch_resp.raise_for_status()
        dispatch_rows = dispatch_resp.json()
        if dispatch_rows:
            dispatch_df = pd.DataFrame(dispatch_rows)
            status_lower = dispatch_df.get("sms_status", pd.Series(dtype=str)).astype(str).str.lower()
            success_count = int(status_lower.str.contains("delivered|sent|success", regex=True).sum())
            total_count = len(dispatch_df)
            success_rate = round(success_count / total_count * 100, 1) if total_count else 0.0
            m1, m2, m3 = st.columns(3)
            m1.metric("Attempts", total_count)
            m2.metric("Successful", success_count)
            m3.metric("Success rate", f"{success_rate:.1f}%")
        else:
            st.info("No dispatches logged yet.")
    except Exception as exc:
        dispatch_rows = None
        st.caption(f"Unable to load recent dispatches: {exc}")

with st.expander("View full dispatch log"):
    if dispatch_rows:
        dispatch_df = dispatch_df.rename(columns={
            "timestamp": "Time", "officer_id": "Officer", "zone_name": "Zone",
            "risk_tier": "Risk", "predicted_violations": "Predicted",
            "distance_km": "Distance", "sms_status": "Status",
            "error_detail": "Error Detail", "recipient_phone": "Recipient",
        })
        st.dataframe(dispatch_df, use_container_width=True, hide_index=True)
        if st.button("Acknowledge latest delivered dispatch"):
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
    else:
        st.caption("Nothing to show yet.")

# ============================================================================
# FOOTER
# ============================================================================
st.markdown("---")
fc1, fc2 = st.columns([3, 1])
with fc1:
    total_records = briefing.get("total_violation_records")
    if total_records is not None:
        st.caption(f"Generated by SENTRI AI — powered by {format_indian(total_records)} violation records")
    else:
        st.caption("Generated by SENTRI AI")
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