
# SENTRI

=======

# SENTRI - Smart Enforcement Network for Traffic Risk Intelligence

>>>>>>> 228d3a7ea5b7ae8db11e3ee09d7c7b3c3d780b20
SENTRI is a Bengaluru parking intelligence platform designed to help enforcement teams detect, prioritize, and respond to parking violations more effectively. The system combines historical violation data, anomaly detection, forecasting, patrol planning, and optional SMS dispatching into a single dashboard.

## Overview

SENTRI answers three core questions:

- Where are violations most likely to happen next?
- Which locations need immediate patrol attention?
- Which patterns look unusual or risky for enforcement teams?

The project is built with:

- Streamlit for the web dashboard
- FastAPI for backend APIs
- Pandas + scikit-learn for analytics
- Prophet for forecasting
- Folium for interactive maps
- Twilio for dispatch SMS notifications

---

## Key Features

### 1. Daily Briefing
A command-center style overview of the current day, including:

- predicted violations for the day
- active hotspot count
- repeat offender summary
- integrity alerts
- top patrol zones
- station performance snapshot

### 2. Patrol Map
An interactive patrol planning view that shows:

- zone-level risk and intensity
- current and future hotspot recommendations
- peak violation windows
- search by junction or station name
- manual hour/day mode and "Patrol tonight" mode

### 3. Violation Forecast
A forecasting dashboard for predicted parking activity over time, including:

- city-level forecasts
- key location forecasts
- peak prediction windows

### 4. Anomaly Detector
Highlights unusual behavior such as:

- suspicious enforcement spikes
- bulk filing bursts
- outlier station activity
- abnormal violation patterns

### 5. Repeat Offenders
Shows repeat violator activity and tracking insights for:

- frequent vehicles
- last-seen zones
- involved stations

### 6. Station Audit
Provides a performance view for stations, including:

- filed cases
- approved cases
- rejected cases
- rejection-rate trends

### 7. Dispatch / SMS Alerts
Allows dispatch actions to send SMS notifications to officers when Twilio credentials are configured.

---

## Project Structure

- `app.py` — main Streamlit dashboard entry point
- `run_api.py` — API startup helper
- `start_app.ps1` — PowerShell script to launch API + UI with environment variables
- `api/` — FastAPI application and backend services
- `pages/` — Streamlit dashboard pages
- `utils/` — shared API wrappers, UI helpers, and formatting utilities
- `ml/` — training and model-related scripts
- `artifacts/` — precomputed model outputs and forecast data
- `data/` — input datasets

---

## Tech Stack

- Python
- Streamlit
- FastAPI
- Uvicorn
- Pandas
- NumPy
- scikit-learn
- Prophet
- Folium
- Plotly
- Twilio
- ReportLab

---

## Environment Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure environment variables

Required variables for SMS dispatch:

- `TWILIO_ACCOUNT_SID`
- `TWILIO_AUTH_TOKEN`
- `TWILIO_PHONE_NUMBER`
- `TWILIO_TO_NUMBER`

Optional runtime variables:

- `SENTRI_API_URL`
- `SENTRI_API_PORT`

You can configure these manually in your shell or use the provided script [start_app.ps1](start_app.ps1).

---

## Running the Application

### Option 1: Use the provided PowerShell startup script

```powershell
./start_app.ps1
```

This script starts:

- the API backend, and
- the Streamlit dashboard

### Option 2: Run both together in one command

```bash
python start_both.py
```

This launches:

- the API backend on port `8000`, and
- the Streamlit UI on port `8501`

### Option 3: Run manually

Start the API:

```bash
python run_api.py
```

Start the dashboard:

```bash
streamlit run app.py
```

---

## API Notes

The backend exposes endpoints for:

- summary statistics
- hotspots and risk data
- anomaly records
- patrol intelligence
- forecast information
- station performance
- repeat offender insights
- dispatch actions and logs

The main API entry point is in [api/main.py](api/main.py).

---

## Data and Artifacts

The application depends on:

- input CSV data in `data/`
- generated forecast and scoring artifacts in `artifacts/`

These artifacts are used to power the dashboard without recomputing everything on every request.

---

## Notes for Developers

- The dashboard pages are designed for operational use, not just static reporting.
- The patrol map and briefing views are optimized for speed and readability.
- Dispatch features depend on Twilio configuration and valid recipient data.
- The project is intended to support future integration with live data feeds and backend services.

---

## License

This project is intended for internal operational and research use.
=======
# SENTRI
SENTRI transforms 298,450 real Bengaluru parking violation records  into a live enforcement command system. Instead of reactive patrolling,  officers receive proactive SMS dispatch orders based on predicted  violation spikes — before congestion forms.

