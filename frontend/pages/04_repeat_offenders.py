import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import plotly.graph_objects as go
import pandas as pd
import streamlit as st
from frontend.utils.api_client import get_repeat_offenders, get_vehicle
from frontend.utils.ui import page_header

# ── Inline CSS ─────────────────────────────────────────────────────────────
st.markdown("""
<style>
/* KPI strip */
.kpi-strip { display:flex; gap:1rem; margin-bottom:1.5rem; }
.kpi-card {
    flex:1; background:#0f1117; border:1px solid #1e2230;
    border-radius:8px; padding:1rem 1.25rem;
}
.kpi-label { font-size:.7rem; letter-spacing:.12em; color:#6b7280; text-transform:uppercase; }
.kpi-value { font-size:1.75rem; font-weight:700; color:#f9fafb; line-height:1.2; }
.kpi-sub   { font-size:.75rem; color:#9ca3af; margin-top:.15rem; }

/* Threat badge */
.tier-badge {
    display:inline-block; font-size:.65rem; font-weight:700;
    letter-spacing:.1em; text-transform:uppercase;
    padding:.2rem .5rem; border-radius:4px;
}
.tier-critical { background:#450a0a; color:#fca5a5; border:1px solid #7f1d1d; }
.tier-high     { background:#431407; color:#fdba74; border:1px solid #7c2d12; }
.tier-watch    { background:#422006; color:#fde68a; border:1px solid #78350f; }

/* Vehicle result card */
.veh-card {
    background:#0f1117; border:1px solid #1e2230; border-radius:8px;
    padding:1.25rem; margin-bottom:1rem;
}
.veh-number { font-size:1.4rem; font-weight:700; color:#f9fafb; letter-spacing:.06em; }
.veh-meta   { font-size:.8rem; color:#9ca3af; margin-top:.3rem; }

/* Search bar label override */
.search-label { font-size:.7rem; letter-spacing:.12em; color:#6b7280;
                text-transform:uppercase; margin-bottom:.35rem; }

/* Section divider */
.section-rule {
    border:none; border-top:1px solid #1e2230; margin:1.5rem 0;
}
</style>
""", unsafe_allow_html=True)

# ── Page header ─────────────────────────────────────────────────────────────
page_header("🔁 Repeat Offenders", "Vehicles with chronic violation history — ranked by threat tier.")

# ── Data fetch ──────────────────────────────────────────────────────────────
data = get_repeat_offenders()
top50 = pd.DataFrame(data["top50"])
dist  = pd.DataFrame(data["distribution"])

# ── Threat tier helper ───────────────────────────────────────────────────────
def tier(n):
    if n >= 20:   return "CRITICAL", "tier-critical"
    if n >= 10:   return "HIGH",     "tier-high"
    return "WATCH", "tier-watch"

top_tier_label, top_tier_cls = tier(data["max_violations"])

# ── KPI strip ────────────────────────────────────────────────────────────────
st.markdown(f"""
<div class="kpi-strip">
  <div class="kpi-card">
    <div class="kpi-label">Chronic offenders (5+ violations)</div>
    <div class="kpi-value">{data['repeat_5plus']:,}</div>
    <div class="kpi-sub">vehicles still active on Bengaluru roads</div>
  </div>
  <div class="kpi-card">
    <div class="kpi-label">Highest violation count</div>
    <div class="kpi-value">{data['max_violations']}</div>
    <div class="kpi-sub">
      {data['top_vehicle']} &nbsp;
      <span class="tier-badge {top_tier_cls}">{top_tier_label}</span>
    </div>
  </div>
  <div class="kpi-card">
    <div class="kpi-label">Top 50 avg violations</div>
    <div class="kpi-value">{top50['violation_count'].mean():.1f}</div>
    <div class="kpi-sub">per vehicle in watchlist</div>
  </div>
</div>
""", unsafe_allow_html=True)

# ── Two-column layout: search | distribution ─────────────────────────────────
col_search, col_chart = st.columns([1, 1], gap="large")

with col_search:
    st.markdown('<div class="search-label">Vehicle lookup</div>', unsafe_allow_html=True)
    search = st.text_input(
        label="vehicle_search",
        label_visibility="collapsed",
        placeholder="e.g. KA01AB1234",
    )

    if search:
        result = get_vehicle(search)
        if result["count"] == 0:
            st.warning(f"No violations on record for **{search.upper()}**.")
        else:
            v_count = result["count"]
            v_num   = result["vehicle_number"]
            t_label, t_cls = tier(v_count)
            hist = pd.DataFrame(result["violations"])

            # Compact result card
            top_station = (
                hist["police_station"].value_counts().idxmax()
                if "police_station" in hist.columns else "—"
            )
            top_type = (
                hist["violation_type_parsed"].value_counts().idxmax()
                if "violation_type_parsed" in hist.columns else "—"
            )
            st.markdown(f"""
            <div class="veh-card">
              <div class="veh-number">
                {v_num}
                &nbsp;<span class="tier-badge {t_cls}">{t_label}</span>
              </div>
              <div class="veh-meta">
                <b>{v_count}</b> violations &nbsp;·&nbsp;
                Most cited at <b>{top_station}</b> &nbsp;·&nbsp;
                Primary offence: <b>{top_type}</b>
              </div>
            </div>
            """, unsafe_allow_html=True)

            # Slim violation log — key columns only
            display_cols = [c for c in ["date", "violation_type_parsed", "police_station", "fine_amount"]
                            if c in hist.columns]
            st.dataframe(
                hist[display_cols] if display_cols else hist,
                use_container_width=True,
                hide_index=True,
                height=260,
            )
    else:
        st.caption("Enter a vehicle number to pull its full violation history.")

with col_chart:
    st.markdown('<div class="search-label">Violation frequency distribution</div>', unsafe_allow_html=True)

    # Colour buckets by implied severity
    import re
    bar_colors = []
    for b in dist["bucket"]:
        # extract the first run of digits regardless of dash character or + suffix
        m = re.search(r"\d+", str(b))
        low = int(m.group()) if m else 0
        if low >= 20:     bar_colors.append("#ef4444")
        elif low >= 10:   bar_colors.append("#f97316")
        else:             bar_colors.append("#3b82f6")

    fig = go.Figure(go.Bar(
        x=dist["bucket"],
        y=dist["vehicles"],
        marker_color=bar_colors,
        text=dist["vehicles"],
        textposition="outside",
        textfont=dict(size=10, color="#9ca3af"),
    ))
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        height=340,
        margin=dict(l=0, r=0, t=8, b=0),
        xaxis=dict(title="Violation bucket", tickfont=dict(size=10)),
        yaxis=dict(title="Vehicles", gridcolor="#1e2230"),
        bargap=0.35,
    )
    st.plotly_chart(fig, use_container_width=True)

st.markdown('<hr class="section-rule"/>', unsafe_allow_html=True)

# ── Top 50 table with threat tier column ─────────────────────────────────────
st.markdown('<div class="search-label">Top 50 watchlist</div>', unsafe_allow_html=True)

if "violation_count" in top50.columns:
    top50.insert(0, "tier", top50["violation_count"].apply(lambda n: tier(n)[0]))

st.dataframe(
    top50,
    use_container_width=True,
    hide_index=True,
    height=380,
    column_config={
        "tier": st.column_config.TextColumn("Tier", width="small"),
        "violation_count": st.column_config.NumberColumn("Violations", format="%d"),
    },
)