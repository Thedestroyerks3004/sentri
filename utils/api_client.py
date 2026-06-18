import os

import requests
import streamlit as st

API_BASE = os.getenv("PARKIQ_API_URL", "http://127.0.0.1:8000")


@st.cache_data(ttl=300, show_spinner=False)
def _get(path: str, params: dict | None = None):
    url = f"{API_BASE}{path}"
    try:
        resp = requests.get(url, params=params, timeout=120)
        resp.raise_for_status()
        return resp.json()
    except requests.HTTPError as exc:
        raise RuntimeError(
            f"API request failed for {url} (HTTP {resp.status_code})"
        ) from exc
    except requests.RequestException as exc:
        raise RuntimeError(f"Unable to reach API at {url}: {exc}") from exc


def api_available() -> bool:
    required_paths = (
        "/api/stats/summary",
        "/api/daily-briefing",
    )
    try:
        return all(
            requests.get(f"{API_BASE}{path}", timeout=30).status_code == 200
            for path in required_paths
        )
    except Exception:
        return False


@st.cache_data(ttl=300, show_spinner=False)
def get_summary() -> dict:
    return _get("/api/stats/summary")


@st.cache_data(ttl=300, show_spinner=False)
def get_hotspots(risk_tier: str | None = None, limit: int = 500) -> list:
    params = {"limit": limit}
    if risk_tier:
        params["risk_tier"] = risk_tier
    return _get("/api/hotspots", params)


@st.cache_data(ttl=300, show_spinner=False)
def get_junctions(limit: int = 50) -> list:
    return _get("/api/junctions", {"limit": limit})


@st.cache_data(ttl=300, show_spinner=False)
def get_anomalies(min_score: float = 0.0, limit: int = 500) -> list:
    return _get("/api/anomalies", {"min_score": min_score, "limit": limit})


@st.cache_data(ttl=300, show_spinner=False)
def get_forecast(location: str) -> dict:
    return _get(f"/api/forecast/{location}")


@st.cache_data(ttl=300, show_spinner=False)
def get_scheduler(hour: int, day: int, limit: int = 10) -> list:
    return _get("/api/scheduler", {"hour": hour, "day": day, "limit": limit})


@st.cache_data(ttl=300, show_spinner=False)
def get_vehicle(vehicle_number: str) -> dict:
    return _get(f"/api/vehicle/{vehicle_number}")


@st.cache_data(ttl=300, show_spinner=False)
def get_night_paradox() -> dict:
    return _get("/api/night-paradox")


@st.cache_data(ttl=300, show_spinner=False)
def get_bulk_filing() -> dict:
    return _get("/api/bulk-filing")


@st.cache_data(ttl=300, show_spinner=False)
def get_station_performance() -> dict:
    return _get("/api/station-performance")


@st.cache_data(ttl=300, show_spinner=False)
def get_repeat_offenders() -> dict:
    return _get("/api/repeat-offenders")


@st.cache_data(ttl=300, show_spinner=False)
def get_feedback_loop(loc_key: str | None = None) -> dict:
    params = {}
    if loc_key:
        params["loc_key"] = loc_key
    return _get("/api/feedback-loop", params)


@st.cache_data(ttl=300, show_spinner=False)
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
    return _get("/api/patrol-map", params)


@st.cache_data(ttl=300, show_spinner=False)
def get_zone_detail(loc_key: str) -> dict:
    return _get(f"/api/zone/{loc_key}")


@st.cache_data(ttl=300, show_spinner=False)
def get_daily_briefing() -> dict:
    return _get("/api/daily-briefing")


@st.cache_data(ttl=300, show_spinner=False)
def get_outcomes() -> dict:
    return _get("/api/outcomes")


def acknowledge_dispatch() -> dict:
    return requests.post(f"{API_BASE}/api/dispatch/acknowledge", timeout=30).json()
