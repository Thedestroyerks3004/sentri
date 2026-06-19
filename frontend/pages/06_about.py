import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import streamlit as st

from frontend.utils.ui import apply_brand, page_header

page_header("ℹ️ About & Integration Guide", "How SENTRI connects to existing Bengaluru enforcement systems.")

apply_brand()

st.markdown("""
## What is SENTRI?

SENTRI transforms **298,450** anonymised parking violation records into actionable enforcement
intelligence using three AI models:

| Model | Purpose |
|-------|---------|
| **Isolation Forest** | Flags anomalous filing patterns (11% of records) |
| **PCIS + KMeans** | Scores every micro-location 0–100 by congestion impact |
| **Facebook Prophet** | Forecasts violations 7 days ahead, city-wide and per junction |

---

## Architecture

```
SCITA Database  →  FastAPI Backend  →  Streamlit Dashboard
     (live)         (6+ endpoints)       (Daily Briefing + Map)
```

The dashboard **never reads CSVs directly**. Every number is computed fresh from the API.

---

## Integration with SCITA

> *"Replace the CSV with a live database connection in the API. The dashboard doesn't change at all."*

1. Point `api/services.py` data loader at the SCITA REST/SQL endpoint
2. Schedule nightly model retraining (`python -m ml.train_all`)
3. Push Daily Briefing PDF to station heads via WhatsApp/SMS webhook

No new hardware. No new devices. Intelligence layered on what already exists.

---

## Judge Q&A

**How is this different from BBMP?**  
BBMP reacts. We predict.

**What if officers ignore the patrol schedule?**  
Non-compliance surfaces as anomalies in the next cycle.

**Where's the ML?**  
Anomaly Detector page + Integrity Alerts in the Daily Briefing.

---

## Demo navigation

1. **Daily Briefing** — what to do (auto-generated every load)
2. **Patrol Map** — where to go (time slider + patrol tonight mode)
3. **Violation Forecast** — why now (Prophet 7-day)
4. **Anomaly Detector** — what's wrong (Isolation Forest)
5. **Station Audit** — who's failing (rejection rates)
""")

