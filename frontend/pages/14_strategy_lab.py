import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from frontend.utils.api_client import simulate_strategy
from frontend.utils.pdf_briefing import generate_strategy_pdf
from frontend.utils.ui import apply_brand, page_header

apply_brand()

page_header("Strategy Lab - What-If Simulation", "Model the impact of increased patrol intensity on violation reduction.")

st.markdown("---")
st.subheader("Simulate Patrol Strategy")

patrol_increase = st.slider("Increase patrol intensity by (%)", 0, 200, 50, 10,
                            help="How much additional patrol coverage to simulate")

if st.button("Run Simulation", type="primary", use_container_width=True):
    with st.spinner("Running what-if analysis..."):
        result = simulate_strategy(patrol_increase)

    if result.get("error"):
        st.error(result["error"])
    else:
        c1, c2, c3, c4 = st.columns(4)
        with c1: st.metric("Current Violations", f"{result['total_current_violations']:,}")
        with c2: st.metric("After Simulation", f"{result['predicted_total_after']:,}", delta=f"-{result['predicted_reduction']:,}")
        with c3: st.metric("Reduction", f"{result['reduction_pct']}%")
        with c4: st.metric("Patrol Increase", f"{result['patrol_increase_pct']}%")

        st.markdown("---")
        st.markdown("### Weekly Projection: Current vs. Simulated")
        projections = pd.DataFrame(result["weekly_projection"])
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=projections["week"], y=projections["current_trend"],
                                mode="lines+markers", name="Current Trend", line=dict(color="#ef4444", width=3)))
        fig.add_trace(go.Scatter(x=projections["week"], y=projections["simulated_trend"],
                                mode="lines+markers", name="With Increased Patrol", line=dict(color="#22c55e", width=3)))
        fig.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                         height=400, xaxis_title="Week", yaxis_title="Violations",
                         legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
        st.plotly_chart(fig, use_container_width=True)

        st.markdown("---")
        st.markdown("### Top Zones Affected")
        zones = pd.DataFrame(result["top_zones_impact"])
        if not zones.empty:
            st.dataframe(zones[["location", "risk_tier", "total_violations", "pcis"]],
                        use_container_width=True, hide_index=True)

        st.caption(f"Elasticity factor: {result['elasticity_factor']}")

        st.markdown("---")
        st.subheader("Export Report")
        pdf_bytes = generate_strategy_pdf(result)
        st.download_button(
            label="📄 Export Simulation PDF",
            data=pdf_bytes,
            file_name=f"sentri_strategy_{pd.Timestamp.now().strftime('%Y%m%d_%H%M')}.pdf",
            mime="application/pdf",
            type="primary",
            use_container_width=False,
        )
        st.caption("PDF includes simulation parameters, weekly projections, and impacted zones with 'SENTRI SIMULATION' watermark.")
else:
    st.info("Adjust the patrol increase slider above and click 'Run Simulation'.")
