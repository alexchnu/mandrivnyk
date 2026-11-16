"""Pedestrian routing through OSRM (foot profile)."""

from __future__ import annotations

import httpx
import numpy as np

from ..config import get_settings
from .http import ProviderError, client

Point = tuple[float, float]  # (lat, lon)


def _coords(points: list[Point]) -> str:
    return ";".join(f"{lon:.6f},{lat:.6f}" for lat, lon in points)


async def table(points: list[Point]) -> tuple[np.ndarray, np.ndarray]:
    """Duration (s) and distance (m) matrices; NaN where no walking path exists."""
    url = f"{get_settings().osrm_url}/table/v1/foot/{_coords(points)}"
    try:
        resp = await client().get(url, params={"annotations": "duration,distance"})
        data = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise ProviderError("Routing service is temporarily unavailable") from exc
    if resp.status_code != 200 or data.get("code") != "Ok":
        raise ProviderError(f"Routing service error: {data.get('code', resp.status_code)}")
    return np.array(data["durations"], float), np.array(data["distances"], float)


async def route(points: list[Point]) -> dict:
    """Walking path through ``points`` in the given order: geometry and legs."""
    url = f"{get_settings().osrm_url}/route/v1/foot/{_coords(points)}"
    try:
        resp = await client().get(url, params={"overview": "full", "geometries": "geojson", "steps": "false"})
        data = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise ProviderError("Routing service is temporarily unavailable") from exc
    if resp.status_code != 200 or data.get("code") != "Ok" or not data.get("routes"):
        raise ProviderError(f"Routing service error: {data.get('code', resp.status_code)}")
    best = data["routes"][0]
    return {
        "geometry": [[lat, lon] for lon, lat in best["geometry"]["coordinates"]],
        "legs": [{"duration_s": leg["duration"], "distance_m": leg["distance"]} for leg in best["legs"]],
        "duration_s": best["duration"],
        "distance_m": best["distance"],
    }
