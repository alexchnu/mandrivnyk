"""Pedestrian routing through OSRM (foot profile)."""

from __future__ import annotations

import asyncio
import time

import httpx
import numpy as np

from ..config import get_settings
from .http import ProviderError, client

Point = tuple[float, float]  # (lat, lon)


def _coords(points: list[Point]) -> str:
    return ";".join(f"{lon:.6f},{lat:.6f}" for lat, lon in points)


_slots = asyncio.Semaphore(2)  # public routing servers reject bursts of parallel requests
_down_until = 0.0  # circuit breaker: monotonic time until which the server is not contacted


def reset() -> None:
    """Close the circuit breaker (used by tests)."""
    global _down_until
    _down_until = 0.0


async def _get_json(url: str, params: dict[str, str]) -> dict:
    """GET with a circuit breaker; at most two requests to the routing server run at a time.

    A gateway error is retried once. A time-out or a rate-limit answer is not: the caller
    falls back to estimates at once, and for ``osrm_cooldown_s`` the server is left alone,
    so an outage costs one slow request instead of slowing every plan down.
    """
    global _down_until
    settings = get_settings()
    if time.monotonic() < _down_until:
        raise ProviderError("Routing service is temporarily unavailable (cooling down)")
    last: Exception | str = "no response"
    async with _slots:
        for attempt in range(2):
            try:
                resp = await client().get(url, params=params, timeout=settings.osrm_timeout_s)
                data = resp.json()
                if resp.status_code == 200 and data.get("code") == "Ok":
                    return data
                last = str(data.get("code", resp.status_code))
                if resp.status_code < 500 and resp.status_code != 429:
                    # a definite answer such as NoRoute: the server works, retrying cannot help
                    raise ProviderError(f"Routing service could not answer ({last})")
                if resp.status_code not in (502, 503, 504):
                    break
            except (httpx.HTTPError, ValueError) as exc:
                last = exc
                break
            if attempt == 0:
                await asyncio.sleep(0.5)
    _down_until = time.monotonic() + settings.osrm_cooldown_s
    raise ProviderError(f"Routing service is temporarily unavailable ({last})")


async def table(points: list[Point]) -> tuple[np.ndarray, np.ndarray]:
    """Duration (s) and distance (m) matrices; NaN where no walking path exists."""
    url = f"{get_settings().osrm_url}/table/v1/foot/{_coords(points)}"
    data = await _get_json(url, {"annotations": "duration,distance"})
    return np.array(data["durations"], float), np.array(data["distances"], float)


async def route(points: list[Point]) -> dict:
    """Walking path through ``points`` in the given order: geometry and legs."""
    url = f"{get_settings().osrm_url}/route/v1/foot/{_coords(points)}"
    data = await _get_json(url, {"overview": "full", "geometries": "geojson", "steps": "false"})
    if not data.get("routes"):
        raise ProviderError("Routing service returned no route")
    best = data["routes"][0]
    return {
        "geometry": [[lat, lon] for lon, lat in best["geometry"]["coordinates"]],
        "legs": [{"duration_s": leg["duration"], "distance_m": leg["distance"]} for leg in best["legs"]],
        "duration_s": best["duration"],
        "distance_m": best["distance"],
    }
