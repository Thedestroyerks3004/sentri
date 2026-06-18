from __future__ import annotations

from math import asin, cos, radians, sin, sqrt

import pandas as pd


def haversine_distance(coord1: tuple[float, float], coord2: tuple[float, float]) -> float:
    """Return distance between two lat/lon coordinates in kilometres."""
    lat1, lon1 = coord1
    lat2, lon2 = coord2

    lat1, lon1, lat2, lon2 = map(radians, (lat1, lon1, lat2, lon2))
    dlat = lat2 - lat1
    dlon = lon2 - lon1

    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    c = 2 * asin(sqrt(a))
    return 6371 * c


def find_nearest_officer(
    hotspot_coord: tuple[float, float],
    officer_df: pd.DataFrame,
) -> dict | None:
    """Return the closest officer to a hotspot coordinate."""
    if officer_df.empty:
        return None

    best = None
    for _, row in officer_df.iterrows():
        distance = haversine_distance(hotspot_coord, (float(row["latitude"]), float(row["longitude"])))
        if best is None or distance < best["distance_km"]:
            best = {
                "officer_id": row.get("created_by_id"),
                "distance_km": float(distance),
                "latitude": float(row.get("latitude", 0.0)),
                "longitude": float(row.get("longitude", 0.0)),
                "police_station": row.get("police_station", ""),
            }

    return best
