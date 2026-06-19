import pandas as pd

PCIS_WEIGHTS = {
    "total_violations": 0.35,
    "night_violations": 0.25,
    "repeat_vehicles": 0.20,
    "commercial_pct": 0.10,
    "peak_concentration": 0.10,
}

RISK_LABELS = ["Low Risk", "Medium Risk", "High Risk", "Critical"]


def _normalize(series: pd.Series) -> pd.Series:
    mx = series.max()
    if mx == 0 or pd.isna(mx):
        return series * 0.0
    return series / mx


def risk_tier_color(tier: str) -> str:
    return {
        "Critical": "#dc2626",
        "High Risk": "#ef4444",
        "Medium Risk": "#f59e0b",
        "Low Risk": "#22c55e",
    }.get(tier, "#94a3b8")
