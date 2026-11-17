"""Response-time and throughput measurements of the running service.

The coursework reported approximate figures ("2-4 s"); here every scenario is
repeated many times and summarised by mean, median, 95th percentile and a
bootstrap confidence interval of the mean.

Run (API must be up, cities imported):
``uv run python -m planner.experiments.loadtest --base http://127.0.0.1:8010``

``--pause`` spaces out the requests that make the service call the public routing
server. For the service's own computation time start the API with routing switched
off (``PLANNER_OSRM_URL=http://127.0.0.1:9``) and pass ``--pause 0``: walking legs
come from the cache or the straight-line estimate and no external call is made.
"""

from __future__ import annotations

import argparse
import asyncio
import time

import httpx
import numpy as np
import pandas as pd

from ..data.paths import RESULTS_DIR
from ..metrics import bootstrap_ci

CITIES = {
    "Чернівці": (48.2921, 25.9358),
    "Львів": (49.8419, 24.0315),
    "Київ": (50.4501, 30.5234),
    "Одеса": (46.4825, 30.7233),
    "Ужгород": (48.6208, 22.2879),
}


async def timed(client: httpx.AsyncClient, method: str, url: str, **kwargs) -> tuple[float, int]:
    start = time.perf_counter()
    resp = await client.request(method, url, **kwargs)
    elapsed = (time.perf_counter() - start) * 1000.0
    if url.endswith("/plans") and resp.status_code == 200:
        _routed.append(bool(resp.json()["routed"]))
    return elapsed, resp.status_code


_routed: list[bool] = []  # whether the plans of the current scenario used real walking paths


def summarise(name: str, samples: list[float], errors: int, extra: dict | None = None) -> dict:
    values = np.array(samples)
    mean, lo, hi = bootstrap_ci(values)
    return {
        "scenario": name, "n": len(values), "errors": errors, "mean_ms": mean, "ci_lo_ms": lo, "ci_hi_ms": hi,
        "p50_ms": float(np.percentile(values, 50)), "p95_ms": float(np.percentile(values, 95)),
        "max_ms": float(values.max()), **(extra or {}),
    }  # fmt: skip


async def sequential(
    client, name: str, calls: list[tuple[str, str, dict]], extra: dict | None = None, pause_s: float = 0.0
) -> dict:
    """Issue the calls one by one; ``pause_s`` spaces out requests that reach a public server."""
    samples, errors = [], 0
    _routed.clear()
    for method, url, kwargs in calls:
        if pause_s:
            await asyncio.sleep(pause_s)
        ms, status = await timed(client, method, url, **kwargs)
        samples.append(ms)
        errors += status >= 400
    extra = dict(extra or {})
    if _routed:
        extra["routed_share"] = float(np.mean(_routed))
    return summarise(name, samples, errors, extra)


async def concurrent(client, name: str, calls: list[tuple[str, str, dict]], level: int) -> dict:
    """Closed-loop load: ``level`` virtual users issue the calls one after another."""
    queue: asyncio.Queue = asyncio.Queue()
    for call in calls:
        queue.put_nowait(call)
    samples: list[float] = []
    errors = 0

    async def user() -> None:
        nonlocal errors
        while True:
            try:
                method, url, kwargs = queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            ms, status = await timed(client, method, url, **kwargs)
            samples.append(ms)
            errors += status >= 400

    start = time.perf_counter()
    await asyncio.gather(*(user() for _ in range(level)))
    elapsed = time.perf_counter() - start
    return summarise(name, samples, errors, {"users": level, "rps": len(samples) / elapsed})


def recommend_calls(n: int, rng: np.random.Generator, radius: float = 3.0, limit: int = 12) -> list:
    calls = []
    names = list(CITIES)
    for i in range(n):
        lat, lon = CITIES[names[i % len(names)]]
        body = {"lat": lat + rng.normal(0, 0.004), "lon": lon + rng.normal(0, 0.006), "radius_km": radius,
                "limit": limit, "lang": "uk"}  # fmt: skip
        calls.append(("POST", "/api/v1/recommendations", {"json": body}))
    return calls


async def main_async(base: str, n: int, pause: float) -> None:
    rng = np.random.default_rng(0)
    rows = []
    limits = httpx.Limits(max_connections=128, max_keepalive_connections=128)
    async with httpx.AsyncClient(base_url=base, timeout=120, limits=limits) as client:
        # warm-up: summaries of the most popular places are fetched from Wikipedia once and cached
        for call in recommend_calls(10, rng):
            await timed(client, *call[:2], **call[2])

        rows.append(await sequential(client, "recommendations, radius 3 km", recommend_calls(n, rng)))
        rows.append(
            await sequential(client, "recommendations, radius 1 km", recommend_calls(n, rng, radius=1.0))
        )
        rows.append(
            await sequential(client, "recommendations, radius 5 km", recommend_calls(n // 2, rng, radius=5.0))
        )
        rows.append(await sequential(client, "health", [("GET", "/api/v1/health", {})] * n))

        # places for planning: the top suggestions of Lviv (enough sights for 15 stops)
        lat, lon = CITIES["Львів"]
        body = {"lat": lat, "lon": lon, "radius_km": 3, "limit": 30, "lang": "uk", "method": "top_k"}
        ids = [p["id"] for p in (await client.post("/api/v1/recommendations", json=body)).json()["items"]]
        # The public routing server must not be flooded: every scenario uses a small fixed set of
        # requests. A paced warm-up pass fills the caches of walking legs and path geometry; the
        # measured passes are then answered without external calls and show the server's own work.
        for size in (5, 10, 15):
            for mode in ("keep_order", "optimize"):
                calls = []
                for _ in range(12):
                    chosen = rng.choice(ids, size=size, replace=False).tolist()
                    plan = {
                        "stops": [{"poi_id": i} for i in chosen],
                        "mode": mode,
                        "start_date": "2026-11-18",
                    }
                    calls.append(("POST", "/api/v1/plans", {"json": plan}))
                await sequential(client, "warm-up", calls, pause_s=pause)
                rows.append(
                    await sequential(client, f"plan {mode}, {size} stops", calls * 5, {"stops": size})
                )
        multi = []
        for _ in range(10):
            chosen = rng.choice(ids, size=15, replace=False).tolist()
            plan = {"stops": [{"poi_id": i} for i in chosen], "mode": "optimize", "days": 3,
                    "start_date": "2026-11-16", "day_end": "15:00"}  # fmt: skip
            multi.append(("POST", "/api/v1/plans", {"json": plan}))
        await sequential(client, "warm-up", multi, pause_s=pause)
        rows.append(await sequential(client, "plan optimize, 15 stops, 3 days (time windows)", multi * 3))

        # Genuinely new orders (random, not seeded): the path geometry is not cached yet, so every
        # plan includes one round trip to the routing server.
        fresh_rng = np.random.default_rng()
        fresh = []
        for _ in range(10 if pause else 0):
            chosen = fresh_rng.choice(ids, size=10, replace=False).tolist()
            plan = {"stops": [{"poi_id": i} for i in chosen], "mode": "optimize", "start_date": "2026-11-18"}
            fresh.append(("POST", "/api/v1/plans", {"json": plan}))
        if fresh:
            name = "plan optimize, 10 stops, new order (with a routing request)"
            rows.append(await sequential(client, name, fresh, pause_s=pause))

        for level in (1, 4, 16, 64):
            rows.append(
                await concurrent(client, "recommendations under load", recommend_calls(n * 2, rng), level)
            )

    df = pd.DataFrame(rows)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(RESULTS_DIR / "perf.csv", index=False)
    pd.set_option("display.width", 220)
    print(df.round(1).to_string(index=False))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8010")
    parser.add_argument("-n", type=int, default=200)
    parser.add_argument("--pause", type=float, default=2.5)
    args = parser.parse_args()
    asyncio.run(main_async(args.base, args.n, args.pause))


if __name__ == "__main__":
    main()
