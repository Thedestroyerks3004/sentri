# SENTRI Project Description

## 1. Project Overview

SENTRI is a Bengaluru parking intelligence dashboard designed to help traffic and enforcement teams predict, prioritize, and respond to parking violations more effectively. The system combines historical violation data, anomaly detection, risk scoring, forecasting, and dispatch automation into a single web-based platform.

The project is built around a simple idea:

- **Detect where violations are most likely to happen**
- **Understand which locations are risky or unstable**
- **Highlight suspicious enforcement patterns**
- **Direct officers to the most relevant patrol zones**
- **Send SMS alerts when needed**

---

## 2. What Problem the Project Solves

Traditional parking enforcement often relies on reactive responses. Officers may patrol areas without knowing which zones are most likely to need attention at a specific time.

SENTRI solves this by giving teams:

- a daily enforcement summary,
- a patrol map for the next few hours,
- forecasting of future violations,
- anomaly detection for suspicious filing behavior,
- repeat offender tracking,
- station performance analysis, and
- optional SMS dispatching.

---

## 3. Main Features

### 3.0 Recent Performance and UX Improvements
During the latest iteration, the project was updated to improve both runtime speed and operational clarity.

These changes include:

- loading the main data artifacts once during API startup instead of recomputing them on every request,
- adding cached API/data fetch behavior so the dashboard avoids repeated backend work,
- capping patrol map payload size and reducing unnecessary map computations,
- optimizing the daily briefing flow to avoid duplicate heavy zone processing,
- adding live spike and freshness indicators to the briefing view,
- displaying dispatch success metrics such as attempt count, successful sends, and success rate,
- adding request timing checks to confirm which endpoints are still slow and which are now fast.

These updates make the dashboard faster to use while also giving supervisors better visibility into the current state of enforcement activity.

### 3.1 Daily Briefing Dashboard
The Daily Briefing page provides a high-level enforcement view for the current day.

It includes:

- city-wide predicted violations,
- active hotspot count,
- repeat offender count for the week,
- integrity alert count,
- top patrol zones for the day,
- anomaly records flagged for review,
- active repeat offenders,
- station performance snapshot.

This page is meant to answer:

- What is happening now?
- Which zones deserve attention today?
- Which stations have high rejection rates?
- Which vehicles or officers are causing concern?

### 3.2 Patrol Map
The Patrol Map is a location-based planning tool that helps answer:

- Where should officers go tonight?
- Which areas have concentration of violations?
- Which zones are most urgent based on risk score and historical behavior?

Features include:

- interactive Folium map,
- circle markers sized by violation intensity,
- color-coded risk levels,
- zone-level details in a side panel,
- search by station or junction name,
- manual mode and "Patrol tonight" mode,
- mini forecast chart for selected zones.

### 3.3 Violation Forecast
This page shows predicted parking violations over the next 7 days.

Supported views:

- city-wide forecast,
- key junction forecasts for:
  - Safina Plaza,
  - KR Market,
  - Elite,
  - Sagar Theatre,
  - Central Street.

Users can see:

- peak predicted hour,
- peak volume,
- total forecast for the period,
- confidence intervals for the forecast.

This page helps teams anticipate demand before it peaks.

### 3.4 Anomaly Detector
This page uses machine learning to detect unusual enforcement and filing behavior.

The system highlights records that do not follow normal patterns, such as:

- unusually high same-second filing counts,
- abnormal station activity,
- suspicious violation distributions,
- outlier enforcement behavior.

The page includes:

- severity threshold slider,
- anomaly score metrics,
- geospatial anomaly visualization,
- list of flagged records.

### 3.5 Repeat Offenders
This feature identifies repeat violators and tracks their history.

It shows:

- vehicles with 5 or more violations,
- top repeat offenders,
- distribution of offender frequency,
- ability to search a vehicle number,
- mapped history of violations for a selected vehicle.

This is useful for identifying chronic violators and supporting enforcement escalation.

### 3.6 Station Audit
This page evaluates station-level enforcement performance.

It tracks:

- total filed cases,
- approved cases,
- rejected cases,
- rejection rate,
- city average rejection rate,
- performance comparisons between stations.

It helps answer:

- Which stations are performing efficiently?
- Which stations may need process review?
- Are rejection rates improving or worsening over time?

### 3.7 About / Integration Guide
This page explains:

- what SENTRI is,
- how the models work,
- how the system connects to existing enforcement infrastructure,
- how it can be integrated with live backend systems later.

---

## 4. Core Backend APIs

The backend is built using FastAPI and exposes multiple endpoints for the dashboard.

### Summary and analytics

- `/api/stats/summary`  
  Returns overall statistics like total violations, night violations, rejection rate, active hotspots, anomaly count, etc.

- `/api/hotspots`  
  Returns hotspot locations ranked by risk.

- `/api/junctions`  
  Returns high-traffic junction information.

- `/api/anomalies`  
  Returns anomaly records with scores and metadata.

- `/api/night-paradox`  
  Provides night-time traffic and violation patterns.

- `/api/bulk-filing`  
  Tracks bulk filing activity and burst events.

- `/api/station-performance`  
  Returns station-level audit performance.

- `/api/repeat-offenders`  
  Returns repeat offender metrics.

### Forecasting and planning endpoints

- `/api/forecast/{location}`  
  Returns forecast data for a specific location.

- `/api/scheduler`  
  Returns recommended zones for a given hour/day.

- `/api/patrol-map`  
  Returns patrol intelligence data for map visualization.

- `/api/zone/{loc_key}`  
  Returns detailed zone data for one location.

- `/api/daily-briefing`  
  Returns the aggregated briefing payload used by the dashboard.

### Dispatch endpoints

- `/api/dispatch/run`  
  Runs the dispatch cycle and sends SMS alerts if configured.

- `/api/dispatch/log`  
  Returns recent dispatch activity and outcomes.

---

## 5. SMS Dispatch Feature

SENTRI includes an automated dispatch feature for sending SMS messages to officers.

### Purpose
The dispatch system is intended to notify officers about:

- zone assignment,
- risk level,
- predicted violations,
- distance to the hotspot,
- station information.

### How it works

1. The system loads recent scheduling recommendations.
2. It identifies the nearest officer for a hotspot.
3. It checks whether the Twilio credentials are available.
4. It builds a message with zone, risk, and prediction details.
5. It sends the message using Twilio.

### Important inputs
The dispatch flow depends on these environment variables:

- `TWILIO_ACCOUNT_SID`
- `TWILIO_AUTH_TOKEN`
- `TWILIO_PHONE_NUMBER`
- `TWILIO_TO_NUMBER`

It also supports per-officer overrides using variables like:

- `OFFICER_PHONE_<OFFICER_ID>`

---

## 6. Machine Learning Components

SENTRI uses several ML-related workflows.

### 6.1 Isolation Forest for anomalies
The anomaly detector uses an Isolation Forest model to identify unusual records.

It considers features such as:

- hour of violation,
- same-second filing count,
- vehicle violation history,
- location violation history,
- modification lag,
- offence code count,
- charge count.

### 6.2 PCIS + KMeans for risk scoring
The system computes a PCIS-style score for each zone using weighted factors such as:

- total violations,
- night violations,
- repeat vehicles,
- commercial share,
- peak concentration.

These scores are clustered to assign risk tiers:

- Low Risk
- Medium Risk
- High Risk
- Critical

### 6.3 Prophet forecasting
The forecasting page uses Prophet to predict future violation activity.

The model generates predictions for:

- the whole city,
- top junction hotspots.

---

## 7. Data Pipeline

The project is designed around precomputed artifact files.

### Input dataset
The main input dataset is:

- `data/parking_violations_clean.csv`

### Generated artifacts
The training pipeline writes outputs to:

- `artifacts/violations_scored.parquet`
- `artifacts/zone_risk.parquet`
- `artifacts/meta.json`
- `artifacts/forecasts/*.json`
- `artifacts/*.pkl` model files

These artifacts are what the API and dashboard use at runtime.

---

## 8. Frontend Architecture

The frontend uses Streamlit and is organized into pages.

The main application file is:

- `app.py`

This file defines the navigation structure and routes users to the relevant dashboard page.

The dashboard pages are:

- Daily Briefing
- Patrol Map
- Violation Forecast
- Anomaly Detector
- Repeat Offenders
- Station Audit
- About / Integration Guide

---

## 9. UI and Styling Features

The project includes custom styling for:

- headers,
- risk banners,
- patrol panels,
- summary cards,
- warning and insight boxes,
- metrics and charts.

The styling is designed to make the dashboard feel like a command-center tool rather than a generic notebook report.

---

## 10. Technical Stack

### Frontend
- Streamlit
- Plotly
- Folium
- Streamlit Folium

### Backend
- FastAPI
- Uvicorn

### Data / ML
- pandas
- numpy
- scikit-learn
- Prophet
- joblib
- pyarrow

### Utilities
- requests
- reportlab
- pytz
- Twilio

---

## 11. How the Project Works End to End

1. Raw violation data is loaded.
2. The training pipeline computes anomaly scores, zone risk scores, and forecasts.
3. These results are stored as parquet/JSON/model artifacts.
4. The FastAPI service reads the artifacts and exposes APIs.
5. The Streamlit dashboard queries those APIs.
6. Users explore the dashboard and can trigger dispatch actions.

This architecture separates:

- data preparation,
- ML modeling,
- API serving,
- dashboard presentation.

---

## 12. Key Benefits

SENTRI gives users the ability to:

- move from reactive enforcement to proactive enforcement,
- prioritize zones based on risk and forecasts,
- identify operational anomalies,
- monitor station inefficiencies,
- understand repeat behavior,
- send alerts to patrol teams.

---

## 13. Best Use Cases

SENTRI is particularly useful for:

- city traffic enforcement teams,
- parking enforcement managers,
- station supervisors,
- urban analytics teams,
- policy planners who want to reduce parking violations.

---

## 14. Summary

SENTRI is a full-featured parking intelligence platform that combines data analysis, forecasting, anomaly detection, geospatial visualization, and dispatch automation. Its main value is in helping teams understand where enforcement effort should be focused and when that effort will have the greatest impact.
