import streamlit as st

BRAND_CSS = """
<style>
    .main-header {
        font-size: 2.4rem;
        font-weight: 800;
        letter-spacing: -0.03em;
        margin-bottom: 0.25rem;
    }
    .tagline {
        color: #94a3b8;
        font-size: 1.05rem;
        margin-bottom: 1.5rem;
    }
    .metric-card {
        background: linear-gradient(145deg, #1e293b 0%, #0f172a 100%);
        border: 1px solid #334155;
        border-radius: 12px;
        padding: 1.1rem 1.25rem;
        min-height: 110px;
    }
    .metric-label {
        color: #94a3b8;
        font-size: 0.85rem;
        text-transform: uppercase;
        letter-spacing: 0.06em;
    }
    .metric-value {
        font-size: 1.75rem;
        font-weight: 700;
        color: #f8fafc;
        margin-top: 0.35rem;
    }
    .metric-sub {
        color: #64748b;
        font-size: 0.9rem;
        margin-top: 0.15rem;
    }
    .insight-box {
        background: #172554;
        border-left: 4px solid #3b82f6;
        padding: 1rem 1.25rem;
        border-radius: 8px;
        margin: 1rem 0;
    }
    .wow-box {
        background: #450a0a;
        border-left: 4px solid #ef4444;
        padding: 1rem 1.25rem;
        border-radius: 8px;
        margin: 1rem 0;
    }
    div[data-testid="stMetricValue"] {
        font-size: 1.6rem;
    }
    .briefing-header {
        background: #1e293b;
        border: 1px solid #334155;
        border-radius: 8px;
        padding: 1rem 1.5rem;
        margin-bottom: 1rem;
    }
    .risk-banner {
        padding: 0.75rem 1.25rem;
        border-radius: 8px;
        font-weight: 700;
        text-align: center;
        margin: 1rem 0;
    }
    .patrol-question {
        font-size: 2rem;
        font-weight: 800;
        text-align: center;
        margin: 1rem 0 0.5rem;
    }
    .zone-panel {
        background: #1e293b;
        border: 1px solid #334155;
        border-radius: 12px;
        padding: 1rem;
        max-height: 620px;
        overflow-y: auto;
    }
    .tier-critical { color: #ef4444; font-weight: 700; }
    .tier-high { color: #f97316; font-weight: 700; }
    .tier-medium { color: #eab308; font-weight: 700; }
    .tier-low { color: #22c55e; font-weight: 700; }
</style>
"""


def apply_brand() -> None:
    st.markdown(BRAND_CSS, unsafe_allow_html=True)


def page_header(title: str, subtitle: str) -> None:
    apply_brand()
    st.markdown(f'<p class="main-header">{title}</p>', unsafe_allow_html=True)
    st.markdown(f'<p class="tagline">{subtitle}</p>', unsafe_allow_html=True)


def insight(text: str) -> None:
    st.markdown(f'<div class="insight-box">{text}</div>', unsafe_allow_html=True)


def wow_moment(text: str) -> None:
    st.markdown(f'<div class="wow-box">{text}</div>', unsafe_allow_html=True)


def format_indian(num: int | float) -> str:
    n = int(round(num))
    s = str(abs(n))
    if len(s) <= 3:
        return str(n)
    last3 = s[-3:]
    rest = s[:-3]
    parts = []
    while len(rest) > 2:
        parts.insert(0, rest[-2:])
        rest = rest[:-2]
    if rest:
        parts.insert(0, rest)
    return ("-" if n < 0 else "") + ",".join(parts + [last3])
