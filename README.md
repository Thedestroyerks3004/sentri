---
title: Sentri API
emoji: 🚔
colorFrom: blue
colorTo: red
sdk: docker
pinned: false
---

# SENTRI

SENTRI is a parking intelligence dashboard for monitoring, forecasting, and responding to traffic and parking violations in Bengaluru. The project combines a FastAPI backend, a Streamlit dashboard, and a lightweight dispatch workflow so teams can understand risk, spot anomalies, and prioritize patrol deployment.

## What this project does

- Shows a live summary of parking violations and enforcement activity.
- Visualizes hotspot zones, patrol recommendations, repeat offenders, and anomaly signals.
- Provides forecasted violation trends for key junctions and citywide patterns.
- Supports dispatch logging and SMS alert workflows for field officers.
- Loads precomputed artifacts so the dashboard can serve insights quickly.

## Core architecture

- **Frontend**: Streamlit web app for dashboards and pages.
- **Backend API**: FastAPI service that exposes analytics endpoints.
- **ML pipeline**: scripts that generate anomaly scores, zone risk scores, and forecasts.
- **Artifacts**: Parquet/JSON outputs used by the API and UI.
- **Dispatch automation**: optional SMS dispatch flow using Twilio and officer location data.

## Tech stack

- Python 3.11+
- FastAPI
- Streamlit
- Pandas / NumPy
- Scikit-learn
- Prophet
- Plotly / Folium
- Requests
- Twilio

## Project layout

- [backend](backend) — API logic, services, and dispatch handlers.
- [frontend](frontend) — Streamlit dashboard and page modules.
- [ml](ml) — model training and artifact generation.
- [artifacts](artifacts) — generated data files used by the app.
- [data](data) — raw/cleaned source datasets.
- [assets](assets) — UI assets and static resources.

## Quick start

### 1) Install dependencies

```bash
pip install -r requirements.txt
```

If the backend has its own requirements file, install that as well:

```bash
pip install -r backend/requirements.txt
```

### 2) Generate analytics artifacts

The API expects precomputed files in [artifacts](artifacts).

```bash
python -m ml.train_all
```

This script produces:

- scored violation data
- zone risk metrics
- forecast JSON files
- metadata summaries

### 3) Run the app locally

The easiest way to start both the API and the dashboard together is:

```bash
python start_both.py
```

This will launch:

- API on `http://127.0.0.1:8000`
- Streamlit UI on `http://127.0.0.1:8501`

You can also run them individually:

```bash
python -m backend.run_api
python -m streamlit run frontend/app.py
```

## Environment variables

The following variables are used by the app and dispatch logic:

- `SENTRI_API_PORT` — backend port (default: `8000`)
- `SENTRI_API_URL` — base URL used by the frontend to call the API
- `TWILIO_ACCOUNT_SID` — Twilio account SID
- `TWILIO_AUTH_TOKEN` — Twilio auth token
- `TWILIO_PHONE_NUMBER` — sender number
- `TWILIO_TO_NUMBER` — default recipient number for dispatch SMS
- `OFFICER_PHONE_<OFFICER_ID>` — optional per-officer override numbers

The PowerShell launcher script [start_app.ps1](start_app.ps1) shows a sample way to configure these values.

## API overview

The backend exposes REST endpoints under `/api` and `/health`.

### Core endpoints

- `GET /health` — check whether the API is running
- `GET /api/stats/summary` — high-level KPI summary
- `GET /api/hotspots` — zone risk and hotspot rankings
- `GET /api/forecast/{location}` — forecast for a location or junction
- `GET /api/patrol-map` — patrol recommendations and map markers
- `GET /api/daily-briefing` — dashboard briefing payload
- `GET /api/repeat-offenders` — repeat vehicle analysis
- `GET /api/station-performance` — station-level performance metrics
- `GET /api/anomalies` — anomaly detection results
- `POST /api/dispatch/run` — trigger dispatch cycle
- `POST /api/dispatch/acknowledge` — acknowledge latest dispatch
- `GET /api/dispatch/log` — fetch dispatch history

## Frontend pages

The main dashboard is defined in [frontend/app.py](frontend/app.py). It loads the pages listed below:

- [frontend/pages/00_daily_briefing.py](frontend/pages/00_daily_briefing.py) — daily intelligence overview
- [frontend/pages/01_patrol_map.py](frontend/pages/01_patrol_map.py) — hotspot and patrol map
- [frontend/pages/02_violation_forecast.py](frontend/pages/02_violation_forecast.py) — forecast views
- [frontend/pages/03_anomaly_detector.py](frontend/pages/03_anomaly_detector.py) — anomaly exploration
- [frontend/pages/04_repeat_offenders.py](frontend/pages/04_repeat_offenders.py) — repeat offender analysis
- [frontend/pages/05_station_audit.py](frontend/pages/05_station_audit.py) — station audit details
- [frontend/pages/06_about.py](frontend/pages/06_about.py) — integration and usage guide

## Data flow

1. Raw violation data is loaded from [data/parking_violations_clean.csv](data/parking_violations_clean.csv).
2. [ml/train_all.py](ml/train_all.py) computes anomaly flags, zone scoring, and forecast models.
3. Results are exported into [artifacts](artifacts).
4. The FastAPI service loads these artifacts during startup.
5. The Streamlit dashboard calls the API to display intelligence and recommendations.

## Dispatch workflow

The dispatch flow uses officer location data and the scheduler output to send targeted alerts.

- [backend/dispatcher.py](backend/dispatcher.py) reads the latest scheduler results.
- It matches hotspots to nearby officers.
- It sends SMS alerts when Twilio credentials are configured.
- It writes outcomes to [dispatch_log.csv](dispatch_log.csv).

## Troubleshooting

- If the API port is busy, [backend/run_api.py](backend/run_api.py) will try to detect a healthy service or choose another port.
- If the Streamlit app cannot reach the backend, confirm `SENTRI_API_URL` is set correctly.
- If artifacts are missing, rerun `python -m ml.train_all`.
- If dispatch messages fail, verify Twilio credentials and officer phone mappings.

## Notes for contributors

- Keep the backend endpoints and dashboard page names aligned.
- Re-run the training pipeline after changing the dataset or model logic.
- Prefer updating docs when adding new pages, endpoints, or environment variables.

## License

This repository is intended for internal operational use and analytics workflows. Update the license information if you intend to distribute or publish the project externally.

