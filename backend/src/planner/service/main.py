"""FastAPI application factory."""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select, text

from .api import auth, discovery, plans, trips
from .config import get_settings
from .db import dispose_engine, session_factory
from .models import Area, Poi, Trip
from .providers import http

log = logging.getLogger("planner")
_started = time.time()
_timings: dict[str, list[float]] = {}


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    await http.close()
    await dispose_engine()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Planner API",
        version="1.0.0",
        description="Interactive planning of walking tourist trips on open geodata.",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"], allow_headers=["*"]
    )

    @app.middleware("http")
    async def record_timing(request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        elapsed = time.perf_counter() - start
        route = request.scope.get("route")
        if route is not None and request.url.path.startswith("/api/"):
            bucket = _timings.setdefault(f"{request.method} {route.path}", [])
            bucket.append(elapsed)
            del bucket[:-500]
        response.headers["Server-Timing"] = f"app;dur={elapsed * 1000:.1f}"
        return response

    for router in (discovery.router, plans.router, trips.router, auth.router):
        app.include_router(router, prefix="/api/v1")

    @app.get("/api/v1/health", tags=["service"])
    async def health() -> dict:
        async with session_factory()() as session:
            await session.execute(text("SELECT 1"))
        return {"status": "ok", "uptime_s": round(time.time() - _started)}

    @app.get("/api/v1/stats", tags=["service"])
    async def stats() -> dict:
        """Operational metrics: data volume and response-time percentiles per endpoint."""
        async with session_factory()() as session:
            counts = {
                "areas": await session.scalar(select(func.count()).select_from(Area)),
                "pois": await session.scalar(select(func.count()).select_from(Poi)),
                "trips": await session.scalar(select(func.count()).select_from(Trip)),
            }
        latency = {}
        for name, values in _timings.items():
            ordered = sorted(values)
            latency[name] = {
                "count": len(ordered),
                "p50_ms": round(ordered[len(ordered) // 2] * 1000, 1),
                "p95_ms": round(ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))] * 1000, 1),
            }
        return {"data": counts, "latency": latency}

    static_dir = Path(__file__).resolve().parents[3] / "static"
    if static_dir.is_dir():  # production image: the built web client is served by the API
        app.mount("/assets", StaticFiles(directory=static_dir / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        async def spa(path: str) -> FileResponse:
            candidate = static_dir / path
            return FileResponse(candidate if path and candidate.is_file() else static_dir / "index.html")

    return app


app = create_app()
