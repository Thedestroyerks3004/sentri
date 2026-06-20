import os

import requests
import streamlit as st

API_BASE = os.getenv("SENTRI_API_URL", "http://127.0.0.1:8000")
CONNECT_TIMEOUT = 3
READ_TIMEOUT = 30


# ── Private HTTP helper (NOT cached — caching a low-level helper causes
#    double-cache stacks in tracebacks and can permanently store error
#    responses until TTL expires) ────────────────────────────────────────────
def _get(path: str, params: dict | None = None):
    url = f"{API_BASE}{path}"
    try:
        resp = requests.get(
            url,
            params=params,
            timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
        )
        resp.raise_for_status()
        return resp.json()
    except requests.HTTPError as exc:
        raise RuntimeError(
            f"API request failed for {url} (HTTP {resp.status_code}): {resp.text[:200]}"
        ) from exc
    except requests.RequestException as exc:
        raise RuntimeError(f"Unable to reach API at {url}: {exc}") from exc


# ── Health check ─────────────────────────────────────────────────────────────
@st.cache_data(ttl=5, show_spinner=False)
def api_available() -> bool:
    try:
        response = requests.get(
            f"{API_BASE}/health",
            timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
        )
        return response.status_code == 200
    except requests.RequestException:
        return False


# ── Public API functions ──────────────────────────────────────────────────────
# Every function catches RuntimeError and returns {"error": "..."} so pages
# can handle failures gracefully with data.get("error") instead of crashing.

@st.cache_data(ttl=60, show_spinner=False)
def get_summary() -> dict:
    try:
        return _get("/api/stats/summary")
    except RuntimeError as e:
        return {"error": str(e)}


@st.cache_data(ttl=60, show_spinner=False)
def get_hotspots(risk_tier: str | None = None, limit: int = 500) -> list:
    params = {"limit": limit}
    if risk_tier:
        params["risk_tier"] = risk_tier
    try:
        return _get("/api/hotspots", params)
    except RuntimeError as e:
        return []


@st.cache_data(ttl=60, show_spinner=False)
def get_junctions(limit: int = 50) -> list:
    try:
        return _get("/api/junctions", {"limit": limit})
    except RuntimeError:
        return []


@st.cache_data(ttl=60, show_spinner=False)
def get_anomalies(min_score: float = 0.0, limit: int = 500) -> list:
    try:
        return _get("/api/anomalies", {"min_score": min_score, "limit": limit})
    except RuntimeError:
        return []


@st.cache_data(ttl=60, show_spinner=False)
def get_forecast(location: str) -> dict:
    try:
        return _get(f"/api/forecast/{location}")
    except RuntimeError as e:
        return {"error": str(e)}


@st.cache_data(ttl=60, show_spinner=False)
def get_scheduler(hour: int, day: int, limit: int = 10) -> list:
    try:
        return _get("/api/scheduler", {"hour": hour, "day": day, "limit": limit})
    except RuntimeError:
        return []


@st.cache_data(ttl=60, show_spinner=False)
def get_vehicle(vehicle_number: str) -> dict:
    try:
        return _get(f"/api/vehicle/{vehicle_number}")
    except RuntimeError as e:
        return {"error": str(e)}


@st.cache_data(ttl=60, show_spinner=False)
def get_night_paradox() -> dict:
    try:
        return _get("/api/night-paradox")
    except RuntimeError as e:
        return {"error": str(e)}


@st.cache_data(ttl=60, show_spinner=False)
def get_bulk_filing() -> dict:
    try:
        return _get("/api/bulk-filing")
    except RuntimeError as e:
        return {"error": str(e)}


@st.cache_data(ttl=60, show_spinner=False)
def get_station_performance() -> dict:
    try:
        return _get("/api/station-performance")
    except RuntimeError as e:
        return {"error": str(e)}


@st.cache_data(ttl=60, show_spinner=False)
def get_repeat_offenders() -> dict:
    try:
        return _get("/api/repeat-offenders")
    except RuntimeError as e:
        return {"error": str(e)}


@st.cache_data(ttl=60, show_spinner=False)
def get_commercial_impact() -> dict:
    try:
        return _get("/api/commercial-impact")
    except RuntimeError as e:
        return {"error": str(e)}


@st.cache_data(ttl=60, show_spinner=False)
def get_offender_fingerprint() -> dict:
    try:
        return _get("/api/offender-fingerprint")
    except RuntimeError as e:
        return {"error": str(e)}


@st.cache_data(ttl=60, show_spinner=False)
def get_feedback_loop(loc_key: str | None = None) -> dict:
    params = {}
    if loc_key:
        params["loc_key"] = loc_key
    try:
        return _get("/api/feedback-loop", params)
    except RuntimeError as e:
        return {"error": str(e)}


@st.cache_data(ttl=60, show_spinner=False)
def get_patrol_map(
    hour: int = 5,
    day: int = 0,
    limit: int = 100,
    patrol_tonight: bool = False,
    search: str | None = None,
) -> dict:
    params = {"hour": hour, "day": day, "limit": limit, "patrol_tonight": patrol_tonight}
    if search:
        params["search"] = search
    try:
        return _get("/api/patrol-map", params)
    except RuntimeError as e:
        return {"error": str(e)}


@st.cache_data(ttl=60, show_spinner=False)
def get_zone_detail(loc_key: str) -> dict:
    try:
        return _get(f"/api/zone/{loc_key}")
    except RuntimeError as e:
        return {"error": str(e)}


@st.cache_data(ttl=60, show_spinner=False)
def get_daily_briefing() -> dict:
    try:
        return _get("/api/daily-briefing")
    except RuntimeError as e:
        return {"error": str(e)}


@st.cache_data(ttl=60, show_spinner=False)
def get_citizen_reports() -> dict:
    try:
        return _get("/api/citizen/reports")
    except RuntimeError as e:
        return {"error": str(e)}


@st.cache_data(ttl=60, show_spinner=False)
def get_citizen_report(tracking_id: str) -> dict:
    try:
        return _get(f"/api/citizen/report/{tracking_id}")
    except RuntimeError as e:
        return {"error": str(e)}


@st.cache_data(ttl=60, show_spinner=False)
def get_system_health() -> dict:
    try:
        return _get("/api/system-health")
    except RuntimeError as e:
        return {"error": str(e)}


@st.cache_data(ttl=30, show_spinner=False)
def simulate_control(lat: float, lon: float, vehicle_type: str) -> dict:
    try:
        return _get("/api/control/simulate", {"lat": lat, "lon": lon, "vehicle_type": vehicle_type})
    except RuntimeError as e:
        return {"error": str(e)}


@st.cache_data(ttl=30, show_spinner=False)
def simulate_strategy(patrol_increase_pct: float = 50.0) -> dict:
    try:
        return _get("/api/strategy/simulate", {"patrol_increase_pct": patrol_increase_pct})
    except RuntimeError as e:
        return {"error": str(e)}


@st.cache_data(ttl=60, show_spinner=False)
def get_analytics_explorer() -> dict:
    try:
        return _get("/api/analytics/explorer")
    except RuntimeError as e:
        return {"error": str(e)}

