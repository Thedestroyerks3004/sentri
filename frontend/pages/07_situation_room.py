import json
import os
import re
from pathlib import Path

import google.generativeai as genai
import pandas as pd
import requests
import streamlit as st

from backend.api import services
from frontend.utils.api_client import api_available, get_summary
from frontend.utils.ui import apply_brand, format_indian, page_header

ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS = ROOT / "artifacts"
OFFICER_LOCATIONS = ROOT / "officer_locations.csv"
API_BASE = os.getenv("SENTRI_API_URL", "http://127.0.0.1:8000").rstrip("/")

st.markdown(
    """
<style>
.intel-card {
    background: #161b22;
    border: 0.5px solid #30363d;
    border-radius: 8px;
    padding: 12px 14px;
    margin-bottom: 10px;
}
.risk-high { color: #f85149; }
.risk-low { color: #3fb950; }
</style>
""",
    unsafe_allow_html=True,
)

apply_brand()
page_header(
    "🧠 Situation Room",
    "Ask SENTRI for a quick, evidence-based briefing using the latest artifact snapshot.",
)

PROMPT_MAP = {
    "Anomalies now": "Summarize the latest anomaly spikes and tell me which zones need immediate review.",
    "Repeat offenders": "Which vehicles are repeating violations and which zones should be prioritized for follow-up?",
    "Daily briefing": "Create a concise daily briefing for the next patrol shift using the latest risk and forecast data.",
    "Impact cost": "What zones have the highest commercial delay cost and fine revenue impact right now?",
    "Station audit": "Which stations are underperforming or showing the highest rejection or filing issues?",
    "Tomorrow forecast": "Which locations are most likely to see the highest violations tomorrow and why?",
}


def _ensure_service_data() -> None:
    if services.store.violations.empty:
        services.store.load()
    if not services.store.forecasts:
        services.store.load()


@st.cache_data(show_spinner=False)
def load_snapshot() -> dict:
    meta_path = ARTIFACTS / "meta.json"
    zone_path = ARTIFACTS / "zone_risk.parquet"
    violations_path = ARTIFACTS / "violations_scored.parquet"

    with open(meta_path, encoding="utf-8") as f:
        meta = json.load(f)

    zone_df = pd.read_parquet(zone_path)
    if "pcis" not in zone_df.columns and "risk_score" in zone_df.columns:
        zone_df["pcis"] = pd.to_numeric(zone_df["risk_score"], errors="coerce")
    if "pcis" not in zone_df.columns and "score" in zone_df.columns:
        zone_df["pcis"] = pd.to_numeric(zone_df["score"], errors="coerce")
    zone_df = zone_df.sort_values(
        by=["pcis" if "pcis" in zone_df.columns else "total_violations"],
        ascending=False,
    )
    top_zone_rows = []
    for _, row in zone_df.head(15).iterrows():
        top_zone_rows.append(
            {
                "location": row.get("location", "Unknown"),
                "police_station": row.get("police_station", "Unknown"),
                "risk_tier": row.get("risk_tier", "Unknown"),
                "pcis": round(float(row.get("pcis", 0) or 0), 2),
                "total_violations": int(row.get("total_violations", 0) or 0),
                "night_violations": int(row.get("night_violations", 0) or 0),
            }
        )

    violations_df = pd.read_parquet(violations_path)
    top_zone_freq = (
        violations_df.groupby("location", dropna=False)
        .size()
        .reset_index(name="violations")
        .sort_values(["violations", "location"], ascending=[False, True])
        .head(10)
    )
    top_repeat_vehicles = (
        violations_df.groupby("vehicle_number", dropna=False)
        .size()
        .reset_index(name="violations")
        .sort_values(["violations", "vehicle_number"], ascending=[False, True])
        .head(10)
    )

    return {
        "meta": meta,
        "top_zones": top_zone_rows,
        "top_zone_frequency": top_zone_freq.to_dict(orient="records"),
        "top_repeat_vehicles": top_repeat_vehicles.to_dict(orient="records"),
    }


@st.cache_data(show_spinner=False)
def load_forecast_slice() -> dict:
    result = {}
    for path in sorted((ARTIFACTS / "forecasts").glob("*.json")):
        if path.name == "index.json":
            continue
        with open(path, encoding="utf-8") as f:
            result[path.stem] = json.load(f)
    return result


@st.cache_data(show_spinner=False)
def load_officer_locations() -> list[dict]:
    if not OFFICER_LOCATIONS.exists():
        return []
    return pd.read_csv(OFFICER_LOCATIONS).to_dict(orient="records")


def build_context_payload(question: str) -> dict:
    _ensure_service_data()
    payload = load_snapshot()
    q = question.lower()

    patrol_keywords = [
        "patrol",
        "where",
        "deploy",
        "send officers",
        "officers",
        "tonight",
        "tomorrow",
        "shift",
    ]
    anomaly_keywords = ["unusual", "anomaly", "strange", "spike", "outlier", "abnormal"]
    repeat_keywords = ["repeat offender", "habitual", "fingerprint", "pattern", "repeat vehicle"]
    cost_keywords = ["cost", "revenue", "commercial", "delay", "delivery corridor", "delay cost"]
    dispatch_keywords = ["dispatch", "send", "deploy now", "dispatch officers", "trigger dispatch"]

    if any(k in q for k in patrol_keywords):
        top_zones = payload["top_zones"]
        forecast_data = load_forecast_slice()
        zone_names = [item["location"] for item in top_zones[:3]]
        forecast_slice = {}
        for zone in zone_names:
            slug = zone.lower().replace(" ", "_").replace("-", "_")
            forecast_slice[zone] = forecast_data.get(slug, [])[:12]
        payload["context_focus"] = "patrol_recommendation"
        payload["forecast_by_top_zone"] = forecast_slice
        payload["officer_locations"] = load_officer_locations()

    if any(k in q for k in anomaly_keywords):
        payload["anomalies"] = services.get_anomalies(min_score=0.05, limit=12)

    if any(k in q for k in repeat_keywords):
        payload["offender_fingerprint"] = services.get_offender_fingerprint()

    if any(k in q for k in cost_keywords):
        payload["commercial_impact"] = services.get_commercial_impact()

    if any(k in q for k in dispatch_keywords):
        payload["dispatch_intent"] = True

    return payload


def parse_json_response(raw: str) -> dict:
    text = raw.strip()
    text = text.replace("```json", "").replace("```", "")
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.S)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
    return {
        "confidence": "medium",
        "locations": [],
        "anomaly": {"zone": "N/A", "score": 0, "description": text[:240]},
        "dispatch_ready": False,
    }


def render_response_card(payload: dict) -> None:
    confidence = str(payload.get("confidence", "medium")).lower()
    locations = payload.get("locations", [])
    anomaly = payload.get("anomaly", {})

    with st.container():
        st.markdown(
            f"<div class='intel-card'><strong>Confidence:</strong> <span class='risk-{confidence if confidence in ('high', 'low') else 'low'}'>{confidence}</span></div>",
            unsafe_allow_html=True,
        )

    if locations:
        with st.container():
            st.markdown(
                "<div class='intel-card'><strong>Priority locations</strong></div>",
                unsafe_allow_html=True,
            )
            for item in locations:
                name = item.get("name", "Unknown")
                violations = item.get("violations", 0)
                risk_tier = item.get("risk_tier", "Unknown")
                reason = item.get("reason", "")
                st.markdown(
                    f"<div class='intel-card'>• <strong>{name}</strong> — {violations} violations · {risk_tier}<br>{reason}</div>",
                    unsafe_allow_html=True,
                )

    with st.container():
        st.markdown(
            "<div class='intel-card'><strong>Anomaly</strong></div>",
            unsafe_allow_html=True,
        )
        zone = anomaly.get("zone", "N/A")
        score = anomaly.get("score", 0)
        description = anomaly.get("description", "No anomaly details provided.")
        st.markdown(
            f"<div class='intel-card'>{zone} · score {score}<br>{description}</div>",
            unsafe_allow_html=True,
        )

    if payload.get("dispatch_ready"):
        st.session_state["dispatch_ready"] = True
        col1, col2 = st.columns([1, 4])
        with col1:
            if st.button("Confirm dispatch"):
                try:
                    resp = requests.post(
                        f"{API_BASE}/api/dispatch/run",
                        timeout=120,
                    )
                    resp.raise_for_status()
                    st.success(
                        f"Dispatch confirmed — {resp.json().get('succeeded', 0)} success(es) reported."
                    )
                except Exception as exc:
                    st.error(f"Dispatch request failed: {exc}")
        with col2:
            if st.button("Dismiss"):
                st.session_state["dispatch_ready"] = False


def is_confirmation(message: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", " ", message.lower()).strip()
    return normalized in {"confirm", "yes", "do it", "proceed", "go ahead"}


snapshot = load_snapshot()

if not os.environ.get("GEMINI_API_KEY"):
    st.warning(
        "Add a GEMINI_API_KEY environment variable or Streamlit secret before using the Situation Room."
    )
    st.stop()


genai.configure(api_key=os.environ["GEMINI_API_KEY"])
model = genai.GenerativeModel("gemini-2.5-flash")

if "messages" not in st.session_state:
    st.session_state.messages = []
if "pending_dispatch" not in st.session_state:
    st.session_state.pending_dispatch = False
if "dispatch_ready" not in st.session_state:
    st.session_state.dispatch_ready = False
if "prefill" not in st.session_state:
    st.session_state.prefill = ""

summary_slot = st.empty()
if api_available():
    try:
        summary = get_summary()
        with summary_slot.container():
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Total violations", format_indian(summary.get("total_violations", 0)))
            c2.metric("Active hotspots", format_indian(summary.get("active_hotspots", 0)))
            c3.metric("Repeat offenders", format_indian(summary.get("repeat_offenders", 0)))
            c4.metric("Anomaly count", format_indian(summary.get("anomaly_count", 0)))
    except Exception:
        summary_slot.info("Summary metrics unavailable right now.")
else:
    summary_slot.warning("Backend is not reachable yet.")

quick_questions = [
    "Where should I deploy 3 officers tonight for max impact?",
    "Which zones are blocking delivery corridors most?",
    "Show me the top repeat offenders this week",
    "Any anomaly spikes I should know about?",
    "Which junction will see the highest violations tomorrow?",
    "Generate a shift briefing for the evening patrol",
]

if not st.session_state.messages:
    st.caption("Choose one of the quick questions below or ask your own.")
    cols = st.columns(2)
    for i, q in enumerate(quick_questions):
        with cols[i % 2]:
            if st.button(q, use_container_width=True, key=f"quick_{i}"):
                st.session_state.messages.append({"role": "user", "content": q})
                st.rerun()

chips = [
    "Anomalies now",
    "Repeat offenders",
    "Daily briefing",
    "Impact cost",
    "Station audit",
    "Tomorrow forecast",
]
cols = st.columns(len(chips))
for i, label in enumerate(chips):
    with cols[i]:
        if st.button(label, use_container_width=True, key=f"chip_{i}"):
            st.session_state.prefill = PROMPT_MAP[label]
            st.session_state.messages.append({"role": "user", "content": PROMPT_MAP[label]})
            st.rerun()

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        if message["role"] == "assistant" and isinstance(message.get("content"), dict):
            render_response_card(message["content"])
        else:
            st.markdown(message["content"])

prompt = st.chat_input(
    "Ask the Situation Room about hotspots, repeat offenders, or patrol priorities"
)
if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    st.rerun()

if st.session_state.messages and st.session_state.messages[-1]["role"] == "user":
    user_input = st.session_state.messages[-1]["content"]
    if st.session_state.pending_dispatch and is_confirmation(user_input):
        with st.spinner("Running the dispatch cycle..."):
            try:
                resp = requests.post(
                    f"{API_BASE}/api/dispatch/run",
                    timeout=120,
                )
                resp.raise_for_status()
                dispatch_result = resp.json()
            except Exception as exc:
                dispatch_result = {"error": str(exc)}
        st.session_state.pending_dispatch = False
        st.session_state.messages.append(
            {
                "role": "assistant",
                "content": dispatch_result if isinstance(dispatch_result, dict) else {"error": str(dispatch_result)},
            }
        )
        st.rerun()

    if st.session_state.pending_dispatch and not is_confirmation(user_input):
        st.session_state.pending_dispatch = False
        st.session_state.messages.append(
            {
                "role": "assistant",
                "content": "Dispatch was not triggered. If you want to run the standard cycle later, ask again.",
            }
        )
        st.rerun()

    recent_turns = st.session_state.messages[-10:]
    history_text = "\n".join(
        f"{'User' if turn['role'] == 'user' else 'Assistant'}: {turn['content'] if isinstance(turn['content'], str) else json.dumps(turn['content'])}"
        for turn in recent_turns
    )
    context_payload = json.dumps(build_context_payload(user_input), ensure_ascii=False, indent=2)
    system_prompt = f"""
You are SENTRI, a parking enforcement intelligence system for Bengaluru Traffic Police.
Always respond as structured JSON with keys: confidence, locations (list with name, violations, risk_tier, reason), anomaly (zone, score, description), dispatch_ready (bool).
Never respond in prose. Ground every claim in the artifact data provided in context.

DATA SNAPSHOT:
{context_payload}
""".strip()

    final_prompt = f"""
{system_prompt}

Conversation History:
{history_text}

Latest User Question:
{user_input}
""".strip()

    with st.spinner("Checking the latest evidence..."):
        try:
            response = model.generate_content(final_prompt)
            answer_text = response.text.strip() if hasattr(response, "text") else str(response)
            payload = parse_json_response(answer_text)
        except Exception as exc:
            payload = {
                "confidence": "medium",
                "locations": [],
                "anomaly": {"zone": "N/A", "score": 0, "description": f"LLM request failed: {exc}"},
                "dispatch_ready": False,
            }

    st.session_state.messages.append({"role": "assistant", "content": payload})
    st.rerun()
