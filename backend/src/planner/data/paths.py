"""Locations of bulky research data (kept outside the repository)."""

from __future__ import annotations

import os
from pathlib import Path

DATA_ROOT = Path(os.environ.get("PLANNER_DATA_ROOT", "/mnt/gamelib/thesis-data"))
FLICKR_DIR = DATA_ROOT / "flickr"
OSM_DIR = DATA_ROOT / "osm"
CACHE_DIR = DATA_ROOT / "cache"
PROCESSED_DIR = DATA_ROOT / "processed"
RESULTS_DIR = Path(__file__).resolve().parents[3] / "experiments" / "results"
