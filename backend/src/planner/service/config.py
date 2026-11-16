"""Runtime configuration (environment variables with the ``PLANNER_`` prefix)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_PACKAGE_DIR = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PLANNER_", env_file=(".env", "../.env"), extra="ignore")

    database_url: str = "postgresql+asyncpg://planner:planner@localhost:5544/planner"
    secret_key: str = "dev-secret-change-me"
    access_token_days: int = 30
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    # External open-data services
    user_agent: str = "planner-thesis/1.0 (tourist trip planner; academic project)"
    overpass_urls: list[str] = [
        "https://overpass-api.de/api/interpreter",
        "https://overpass.private.coffee/api/interpreter",
        "https://overpass.kumi.systems/api/interpreter",
    ]
    osrm_url: str = "https://routing.openstreetmap.de/routed-foot"
    photon_url: str = "https://photon.komoot.io"
    http_timeout_s: float = 25.0

    # Recommendation defaults (chosen in experiment E3)
    model_dir: Path = _PACKAGE_DIR / "ranking" / "artifacts"
    distance_weight: float = 0.15
    diversity_lambda: float = 0.25
    pool_size: int = 100
    page_size: int = 12
    max_radius_km: float = 10.0

    # Data freshness
    area_radius_km: float = 6.0
    area_ttl_days: int = 30
    walk_speed_m_s: float = 1.25
    detour_factor: float = 1.3


@lru_cache
def get_settings() -> Settings:
    return Settings()
