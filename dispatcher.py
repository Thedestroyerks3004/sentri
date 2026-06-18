from __future__ import annotations

import csv
import os
from datetime import datetime
from pathlib import Path

import pandas as pd

import requests
from twilio.rest import Client

from api import services
from dispatch_utils import find_nearest_officer

ROOT = Path(__file__).resolve().parent
LOG_PATH = ROOT / "dispatch_log.csv"
DEBUG_LOG_PATH = ROOT / "dispatch_debug.log"
OFFICER_LOC_PATH = ROOT / "officer_locations.csv"
LOG_FIELDS = [
    "timestamp",
    "officer_id",
    "zone_name",
    "risk_tier",
    "predicted_violations",
    "distance_km",
    "station_name",
    "sms_status",
    "error_detail",
    "recipient_phone",
    "acknowledged_at",
]


def _normalize_phone(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = text.replace(".0", "")
    if text.isdigit() and not text.startswith("+"):
        return f"+{text}"
    return text


def _read_env(name: str) -> str:
    return (os.getenv(name) or "").strip()


def get_twilio_config() -> dict[str, str]:
    return {
        "account_sid": _read_env("TWILIO_ACCOUNT_SID"),
        "auth_token": _read_env("TWILIO_AUTH_TOKEN"),
        "from_number": _read_env("TWILIO_PHONE_NUMBER"),
        "to_number_default": _read_env("TWILIO_TO_NUMBER"),
    }


def ensure_officer_locations_file() -> pd.DataFrame:
    """Create officer_locations.csv from the loaded violation dataset if needed."""
    if OFFICER_LOC_PATH.exists():
        return pd.read_csv(OFFICER_LOC_PATH)

    if services.store.violations.empty:
        services.store.load()

    df = services.store.violations.copy()
    if df.empty:
        return pd.DataFrame(columns=[
            "created_by_id",
            "latitude",
            "longitude",
            "police_station",
            "created_datetime",
        ])

    df = df.dropna(subset=["created_by_id", "created_datetime", "latitude", "longitude"]).copy()
    df["created_datetime"] = pd.to_datetime(df["created_datetime"], errors="coerce")
    df = df.dropna(subset=["created_datetime"])
    df = df.sort_values("created_datetime", ascending=False)
    latest = df.drop_duplicates(subset=["created_by_id"], keep="first")
    latest = latest[
        ["created_by_id", "latitude", "longitude", "police_station", "created_datetime"]
    ].copy()
    latest.to_csv(OFFICER_LOC_PATH, index=False)
    return latest


def build_sms_message(
    officer_id: str,
    zone_name: str,
    risk_tier: str,
    peak_window: str,
    predicted_violations: int,
    distance_km: float,
    station_name: str,
) -> str:
    return (
        f"Dispatch Alert for Officer {officer_id}\n"
        f"Zone: {zone_name}\n"
        f"Risk: {risk_tier}\n"
        f"Peak Window: {peak_window}\n"
        f"Predicted Violations: {predicted_violations}\n"
        f"Distance: {distance_km:.2f} km\n"
        f"Station: {station_name}"
    )


def send_dispatch(
    officer_id: str,
    zone_name: str,
    risk_tier: str,
    peak_window: str,
    predicted_violations: int,
    distance_km: float,
    station_name: str,
    officer_phone: str,
) -> tuple[bool, str]:
    config = get_twilio_config()
    missing = [
        key
        for key, value in (
            ("TWILIO_ACCOUNT_SID", config["account_sid"]),
            ("TWILIO_AUTH_TOKEN", config["auth_token"]),
            ("TWILIO_PHONE_NUMBER", config["from_number"]),
        )
        if not value
    ]
    if missing:
        reason = f"missing Twilio config: {', '.join(missing)}"
        print(reason)
        return False, reason

    if not officer_phone:
        reason = f"missing recipient phone number for officer {officer_id}"
        print(reason)
        return False, reason

    message = build_sms_message(
        officer_id=officer_id,
        zone_name=zone_name,
        risk_tier=risk_tier,
        peak_window=peak_window,
        predicted_violations=predicted_violations,
        distance_km=distance_km,
        station_name=station_name,
    )

    try:
        client = Client(config["account_sid"], config["auth_token"])
        client.messages.create(
            body=message,
            from_=config["from_number"],
            to=officer_phone,
        )
        print(f"Dispatch SMS sent to {officer_id} ({officer_phone})")
        return True, ""
    except Exception as exc:
        reason = f"Dispatch SMS failed for {officer_id}: {type(exc).__name__}: {exc}"
        print(reason)
        return False, reason


def log_debug_event(message: str) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with DEBUG_LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(f"[{timestamp}] {message}\n")


def normalize_dispatch_log() -> None:
    if not LOG_PATH.exists():
        return

    rows = []
    with LOG_PATH.open("r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        try:
            header = next(reader)
        except StopIteration:
            return

        for row in reader:
            if not row:
                continue
            if len(row) < len(LOG_FIELDS):
                row = row + [""] * (len(LOG_FIELDS) - len(row))
            elif len(row) > len(LOG_FIELDS):
                row = row[: len(LOG_FIELDS)]
            if len(row) >= 10:
                row[9] = _normalize_phone(row[9])
            if len(row) >= 11:
                row[10] = row[10] if row[10] != "nan" else ""
            rows.append(row)

    with LOG_PATH.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(LOG_FIELDS)
        writer.writerows(rows)


def log_dispatch(
    officer_id: str,
    zone_name: str,
    risk_tier: str,
    predicted_violations: int,
    distance_km: float,
    station_name: str,
    sms_status: str,
    error_detail: str = "",
    recipient_phone: str = "",
) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    file_exists = LOG_PATH.exists()
    if file_exists:
        normalize_dispatch_log()
    with LOG_PATH.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=LOG_FIELDS)
        if not file_exists:
            writer.writeheader()
        writer.writerow(
            {
                "timestamp": timestamp,
                "officer_id": officer_id,
                "zone_name": zone_name,
                "risk_tier": risk_tier,
                "predicted_violations": predicted_violations,
                "distance_km": f"{distance_km:.2f}",
                "station_name": station_name,
                "sms_status": sms_status,
                "error_detail": error_detail,
                "recipient_phone": recipient_phone,
            }
        )

    log_debug_event(
        f"officer={officer_id} zone={zone_name} status={sms_status} "
        f"recipient={recipient_phone or 'n/a'} error={error_detail or 'n/a'}"
    )


def read_dispatch_log(limit: int = 20) -> list[dict]:
    if not LOG_PATH.exists():
        return []

    normalize_dispatch_log()
    with LOG_PATH.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    rows = rows[-limit:] if limit else rows
    return rows


def acknowledge_latest_dispatch() -> dict:
    if not LOG_PATH.exists():
        return {"acknowledged": False, "error": "No dispatch log found"}

    normalize_dispatch_log()
    df = pd.read_csv(LOG_PATH, dtype=str)
    if df.empty:
        return {"acknowledged": False, "error": "No dispatch items found"}

    match = df[df["sms_status"].astype(str).str.lower().eq("delivered")].tail(1)
    if match.empty:
        return {"acknowledged": False, "error": "No delivered dispatch to acknowledge"}

    idx = int(match.index[0])
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    df.at[idx, "sms_status"] = "Acknowledged"
    df.at[idx, "acknowledged_at"] = timestamp
    df.to_csv(LOG_PATH, index=False)
    return {"acknowledged": True, "index": idx, "acknowledged_at": timestamp}


def run_dispatch_cycle() -> dict:
    if services.store.violations.empty:
        services.store.load()

    officers = ensure_officer_locations_file()
    if officers.empty:
        log_debug_event("run_dispatch_cycle: no officer locations available")
        return {
            "dispatched": 0,
            "succeeded": 0,
            "error": "no officer locations available",
        }

    api_base = os.getenv("SENTRI_API_URL", "http://127.0.0.1:8000").rstrip("/")

    try:
        scheduler_response = requests.get(
            f"{api_base}/api/scheduler",
            params={"hour": datetime.now().hour, "day": datetime.now().weekday(), "limit": 3},
            timeout=30,
        )
        scheduler_response.raise_for_status()
        scheduler_data = scheduler_response.json()
    except Exception as exc:
        log_debug_event(f"run_dispatch_cycle: scheduler request failed: {exc}")
        return {
            "dispatched": 0,
            "succeeded": 0,
            "error": f"scheduler request failed: {exc}",
        }

    dispatched = 0
    succeeded = 0
    failure_details: list[str] = []

    for zone in scheduler_data[:3]:
        zone_name = zone.get("location", "Unknown Zone")
        risk_tier = zone.get("risk_tier", "Unknown")
        peak_window = zone.get("peak_window", "")
        predicted_violations = int(zone.get("predicted_violations", 0) or 0)
        station_name = zone.get("police_station", "")
        hotspot_lat = zone.get("latitude")
        hotspot_lon = zone.get("longitude")

        if hotspot_lat is None or hotspot_lon is None:
            continue

        nearest = find_nearest_officer((float(hotspot_lat), float(hotspot_lon)), officers)
        if not nearest:
            continue

        officer_id = nearest["officer_id"]
        distance = nearest["distance_km"]
        officer_phone = _read_env(f"OFFICER_PHONE_{officer_id}")
        if not officer_phone:
            officer_phone = get_twilio_config()["to_number_default"]

        if not officer_phone:
            failure_details.append(
                f"No recipient phone number available for officer {officer_id} (expected OFFICER_PHONE_{officer_id} or TWILIO_TO_NUMBER)."
            )
            log_dispatch(
                officer_id=officer_id,
                zone_name=zone_name,
                risk_tier=risk_tier,
                predicted_violations=predicted_violations,
                distance_km=distance,
                station_name=station_name,
                sms_status="failed (missing recipient phone)",
                error_detail="No recipient phone number available for this officer.",
                recipient_phone="",
            )
            continue

        dispatched += 1
        sent, reason = send_dispatch(
            officer_id=officer_id,
            zone_name=zone_name,
            risk_tier=risk_tier,
            peak_window=peak_window,
            predicted_violations=predicted_violations,
            distance_km=distance,
            station_name=station_name,
            officer_phone=officer_phone,
        )
        if sent:
            succeeded += 1
            status = "delivered"
        else:
            status = f"failed ({reason})"
            failure_details.append(reason)

        log_dispatch(
            officer_id=officer_id,
            zone_name=zone_name,
            risk_tier=risk_tier,
            predicted_violations=predicted_violations,
            distance_km=distance,
            station_name=station_name,
            sms_status=status,
            error_detail=reason if not sent else "",
            recipient_phone=officer_phone,
        )

    response = {
        "dispatched": dispatched,
        "succeeded": succeeded,
        "zones_checked": len(scheduler_data[:3]),
    }
    if failure_details:
        response["failure_details"] = failure_details
    return response
