import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd
import streamlit as st
from frontend.utils.api_client import get_offender_fingerprint
from frontend.utils.ui import page_header

# ── Injected styles ──────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=Inter:wght@400;500&family=JetBrains+Mono:wght@400;500&display=swap');

/* Root overrides */
[data-testid="stHeader"] { background: transparent; }
section[data-testid="stMain"] > div { padding-top: 1.5rem; }

/* Page title block */
.fp-title {
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.18em;
    text-transform: uppercase;
    color: #8B949E;
    margin-bottom: 2px;
}
.fp-heading {
    font-size: 26px;
    font-weight: 700;
    color: #E6EDF3;
    margin: 0 0 4px 0;
    letter-spacing: -0.01em;
}
.fp-sub {
    font-size: 13px;
    color: #8B949E;
    margin-bottom: 28px;
}

/* Dossier card */
.dossier-card {
    background: #1f1781;
    border: 1px solid #1C2030;
    border-radius: 6px;
    overflow: hidden;
    margin-bottom: 4px;
    position: relative;
}
.dossier-header {
    display: flex;
    align-items: flex-start;
    gap: 14px;
    padding: 18px 20px 16px 0;
    position: relative;
}
.dossier-stripe {
    width: 4px;
    min-height: 90px;
    align-self: stretch;
    flex-shrink: 0;
}
.dossier-icon {
    font-size: 22px;
    margin-top: 2px;
    flex-shrink: 0;
}
.dossier-body { flex: 1; }
.dossier-archetype {
    font-family: 'Space Grotesk', sans-serif;
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 0.16em;
    text-transform: uppercase;
    color: #8B949E;
    margin-bottom: 4px;
}
.dossier-count {
    font-family: 'Space Grotesk', sans-serif;
    font-size: 40px;
    font-weight: 700;
    line-height: 1;
    margin-bottom: 6px;
}
.dossier-label {
    font-family: 'Inter', sans-serif;
    font-size: 13px;
    color: #8B949E;
    font-weight: 400;
}
.dossier-rec {
    margin: 0 16px 16px 20px;
    padding: 9px 12px;
    background: #0A0C10;
    border-left: 2px solid #1C2030;
    border-radius: 3px;
    font-family: 'Inter', sans-serif;
    font-size: 12px;
    color: #8B949E;
    line-height: 1.5;
}
.dossier-rec strong {
    font-family: 'Space Grotesk', sans-serif;
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    display: block;
    margin-bottom: 3px;
    color: #6E7681;
}

/* Divider */
.fp-divider {
    height: 1px;
    background: #1C2030;
    margin: 20px 0;
}

/* Section header for vehicle tables */
.fp-section-label {
    font-family: 'Space Grotesk', sans-serif;
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 0.16em;
    text-transform: uppercase;
    color: #6E7681;
    padding: 10px 0 8px 0;
    border-bottom: 1px solid #1C2030;
    margin-bottom: 10px;
}

/* Dataframe overrides */
[data-testid="stDataFrame"] {
    border: 1px solid #1C2030;
    border-radius: 4px;
    overflow: hidden;
}
[data-testid="stDataFrame"] table { font-family: 'JetBrains Mono', monospace !important; font-size: 12px !important; }
[data-testid="stDataFrame"] th { background: #0A0C10 !important; color: #6E7681 !important; font-size: 10px !important; letter-spacing: 0.1em !important; text-transform: uppercase !important; }

/* Empty state */
.fp-empty {
    font-family: 'JetBrains Mono', monospace;
    font-size: 12px;
    color: #3D444D;
    padding: 20px 0;
    text-align: center;
    letter-spacing: 0.05em;
}

/* Expander overrides */
[data-testid="stExpander"] {
    background: #111318 !important;
    border: 1px solid #1C2030 !important;
    border-radius: 4px !important;
}
[data-testid="stExpander"] summary {
    font-family: 'Space Grotesk', sans-serif !important;
    font-size: 12px !important;
    font-weight: 500 !important;
    color: #8B949E !important;
    letter-spacing: 0.05em !important;
}

/* Status badges */
.status-row {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 24px;
}
.status-dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: #3B9EFF;
    box-shadow: 0 0 6px #3B9EFF88;
    animation: pulse 2.4s ease-in-out infinite;
}
@keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.4; }
}
.status-text {
    font-family: 'JetBrains Mono', monospace;
    font-size: 11px;
    color: #3B9EFF;
    letter-spacing: 0.08em;
}
</style>
""", unsafe_allow_html=True)

# ── Page header ───────────────────────────────────────────────────────────────
st.markdown('<div class="fp-title">SENTRI · Enforcement Intelligence</div>', unsafe_allow_html=True)
st.markdown('<div class="fp-heading">Offender Fingerprint</div>', unsafe_allow_html=True)
st.markdown('<div class="fp-sub">Pattern-based behavioural classification for repeat vehicle offenders.</div>', unsafe_allow_html=True)
st.markdown("""
<div class="status-row">
    <div class="status-dot"></div>
    <div class="status-text">LIVE CLASSIFICATION ACTIVE</div>
</div>
""", unsafe_allow_html=True)

# ── Data fetch ────────────────────────────────────────────────────────────────
data = get_offender_fingerprint()
if data.get("error"):
    st.warning(data["error"])
    st.stop()

habitual    = data.get("habitual", {})
opportunistic = data.get("opportunistic", {})
organized   = data.get("organized_clusters", [])

# ── Archetype config ──────────────────────────────────────────────────────────
archetypes = [
    {
        "key": "habitual",
        "label": "Habitual Offender",
        "icon": "🔴",
        "color": "#E05C5C",
        "count": habitual.get("count", 0),
        "unit": "vehicles",
        "rec": "Issue warning notices · Review signage at recurring hotspot locations",
        "vehicles": habitual.get("vehicles", []),
        "is_cluster": False,
    },
    {
        "key": "opportunistic",
        "label": "Opportunistic",
        "icon": "🟡",
        "color": "#F0A500",
        "count": opportunistic.get("count", 0),
        "unit": "vehicles",
        "rec": "Deploy targeted patrols during identified peak violation windows",
        "vehicles": opportunistic.get("vehicles", []),
        "is_cluster": False,
    },
    {
        "key": "organized_clusters",
        "label": "Organised Cluster",
        "icon": "🔵",
        "color": "#3B9EFF",
        "count": len(organized),
        "unit": "clusters",
        "rec": "Investigate shared depot or business affiliation across cluster members",
        "vehicles": organized,
        "is_cluster": True,
    },
]

# ── Dossier cards ─────────────────────────────────────────────────────────────
cols = st.columns(3, gap="small")

for col, arch in zip(cols, archetypes):
    with col:
        st.markdown(f"""
        <div class="dossier-card">
            <div class="dossier-header">
                <div class="dossier-stripe" style="background:{arch['color']};"></div>
                <div class="dossier-icon">{arch['icon']}</div>
                <div class="dossier-body">
                    <div class="dossier-archetype">{arch['label']}</div>
                    <div class="dossier-count" style="color:{arch['color']};">{arch['count']}</div>
                    <div class="dossier-label">{arch['unit']} flagged</div>
                </div>
            </div>
            <div class="dossier-rec">
                <strong>Tactical Recommendation</strong>
                {arch['rec']}
            </div>
        </div>
        """, unsafe_allow_html=True)

# ── Divider ───────────────────────────────────────────────────────────────────
st.markdown('<div class="fp-divider"></div>', unsafe_allow_html=True)

# ── Vehicle / cluster tables ──────────────────────────────────────────────────
for arch in archetypes:
    label = f"{arch['label']} — Vehicle Records"
    with st.expander(label, expanded=False):
        vehicles = arch["vehicles"]
        if not vehicles:
            msg = "NO CLUSTERS DETECTED" if arch["is_cluster"] else "NO VEHICLES IN THIS CATEGORY"
            st.markdown(f'<div class="fp-empty">// {msg}</div>', unsafe_allow_html=True)
        else:
            st.dataframe(
                pd.DataFrame(vehicles),
                use_container_width=True,
                hide_index=True,
            )