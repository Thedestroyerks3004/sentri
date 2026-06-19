import json
import os
from pathlib import Path

import google.generativeai as genai
import pandas as pd
import streamlit as st

from frontend.utils.ui import apply_brand, page_header

ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS = ROOT / "artifacts"

apply_brand()
page_header(
    "🧠 Situation Room",
    "Ask SENTRI for a quick, evidence-based briefing using the latest artifact snapshot.",
)


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

quick_questions = [
    "Where should I deploy 3 officers tonight for max impact?",
    "Which zones are blocking delivery corridors most?",
    "Show me the top repeat offenders this week",
    "Any anomaly spikes I should know about?",
    "Which junction will see the highest violations tomorrow?",
    "Generate a shift briefing for the evening patrol",
]

context_payload = json.dumps(snapshot, ensure_ascii=False, indent=2)
system_prompt = f"""
You are SENTRI's AI Situation Room — an expert in parking enforcement and patrol deployment for Bengaluru Traffic Police.

Answer every question using ONLY the data snapshot provided. Be specific — cite zone names, risk scores, and vehicle numbers from the data.

Format every response as:
1. Direct answer (1–2 sentences)
2. Evidence from data (up to 5 bullet points)
3. One concrete next action

Keep responses under 200 words unless asked for a full report.
When asked about maps, tell the officer which map layer to open and what to look for.

DATA SNAPSHOT:
{context_payload}
""".strip()

if not st.session_state.messages:
    st.caption("Choose one of the quick questions below or ask your own.")
    cols = st.columns(2)
    for i, q in enumerate(quick_questions):
        with cols[i % 2]:
            if st.button(q, use_container_width=True, key=f"quick_{i}"):
                st.session_state.messages.append({"role": "user", "content": q})
                st.rerun()

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

prompt = st.chat_input(
    "Ask the Situation Room about hotspots, repeat offenders, or patrol priorities"
)
if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    st.rerun()

if st.session_state.messages and st.session_state.messages[-1]["role"] == "user":
    user_input = st.session_state.messages[-1]["content"]
    recent_turns = st.session_state.messages[-10:]
    history_text = "\n".join(
        f"{'User' if turn['role'] == 'user' else 'Assistant'}: {turn['content']}"
        for turn in recent_turns
    )
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
            answer = response.text.strip() if hasattr(response, "text") else str(response)
        except Exception as exc:
            answer = f"I couldn't generate a response right now. Error: {exc}"

    st.session_state.messages.append({"role": "assistant", "content": answer})
    st.rerun()
