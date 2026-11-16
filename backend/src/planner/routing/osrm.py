"""Walking distances from OSRM (pedestrian profile).

The coursework queried the public demo server, whose only profile is ``driving``;
walking routes then follow one-way streets and avoid pedestrian zones. Here the
``foot`` profile is used explicitly.
"""

from __future__ import annotations

import time

import httpx
import numpy as np

FOOT_URL = "https://routing.openstreetmap.de/routed-foot"
USER_AGENT = "planner-thesis-research/0.1 (academic project)"


WALK_SPEED_M_S = 1.25  # 4.5 km/h, used only where the router finds no path
DETOUR_FACTOR = 1.3  # typical ratio of walking distance to straight-line distance


def table(
    lats, lons, base_url: str = FOOT_URL, block: int = 45, pause_s: float = 1.0
) -> tuple[np.ndarray, np.ndarray]:
    """Full duration (s) and distance (m) matrices between points.

    Requests are split into blocks because public servers limit the number of
    coordinates per call. Pairs without a walking path (e.g. islands reachable
    only by ferry) are filled with a straight-line estimate.
    """
    from ..geo import distance_matrix_m

    lats, lons = np.asarray(lats, float), np.asarray(lons, float)
    n = len(lats)
    duration = np.full((n, n), np.nan)
    distance = np.full((n, n), np.nan)
    blocks = [list(range(i, min(i + block, n))) for i in range(0, n, block)]
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=120) as http:
        for rows in blocks:
            for cols in blocks:
                same = rows == cols
                idx = rows if same else rows + cols
                coords = ";".join(f"{lons[i]:.6f},{lats[i]:.6f}" for i in idx)
                params = {"annotations": "duration,distance"}
                if not same:
                    params["sources"] = ";".join(str(k) for k in range(len(rows)))
                    params["destinations"] = ";".join(str(len(rows) + k) for k in range(len(cols)))
                problem = "no response"
                for attempt in range(6):
                    try:
                        resp = http.get(f"{base_url}/table/v1/foot/{coords}", params=params)
                        if resp.status_code == 200 and resp.json().get("code") == "Ok":
                            break
                        problem = f"HTTP {resp.status_code} {resp.text[:200]}"
                    except (
                        httpx.HTTPError,
                        ValueError,
                    ) as exc:  # the public server drops connections under load
                        problem = repr(exc)
                    time.sleep(2 ** (attempt + 1))
                else:
                    raise RuntimeError(f"OSRM table failed: {problem}")
                data = resp.json()
                duration[np.ix_(rows, cols)] = np.array(data["durations"], float)
                distance[np.ix_(rows, cols)] = np.array(data["distances"], float)
                time.sleep(pause_s)
    missing = np.isnan(duration) | np.isnan(distance)
    if missing.any():
        crow = distance_matrix_m(lats, lons) * DETOUR_FACTOR
        distance[missing] = crow[missing]
        duration[missing] = crow[missing] / WALK_SPEED_M_S
    return duration, distance
