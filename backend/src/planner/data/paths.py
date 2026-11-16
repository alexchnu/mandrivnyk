"""Locations of bulky research data (kept outside the repository)."""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]


def _data_root() -> Path:
    """``PLANNER_DATA_ROOT`` from the environment or the repository's ``.env``; ``.data`` otherwise."""
    value = os.environ.get("PLANNER_DATA_ROOT")
    env_file = REPO_ROOT / ".env"
    if not value and env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            key, _, rest = line.partition("=")
            if key.strip() == "PLANNER_DATA_ROOT":
                value = rest.strip().strip("\"'")
    return (REPO_ROOT / value).resolve() if value else REPO_ROOT / ".data"  # absolute values stay as they are


DATA_ROOT = _data_root()
FLICKR_DIR = DATA_ROOT / "flickr"
OSM_DIR = DATA_ROOT / "osm"
CACHE_DIR = DATA_ROOT / "cache"
PROCESSED_DIR = DATA_ROOT / "processed"
RESULTS_DIR = Path(__file__).resolve().parents[3] / "experiments" / "results"
