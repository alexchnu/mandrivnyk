"""Relevance of a POI = output of the significance model chosen in experiment E2."""

from __future__ import annotations

import logging
from functools import lru_cache

import numpy as np
import pandas as pd

from ..ranking import model as rm
from ..ranking.features import manual_popularity
from .config import get_settings

log = logging.getLogger(__name__)
SERVICE_CATEGORIES = ("food", "nightlife")  # no ground truth in the training data
SERVICE_RELEVANCE_CAP = 0.5


@lru_cache
def _artifact(feature_set: str) -> dict | None:
    path = get_settings().model_dir / f"significance_{feature_set.replace('+', '_')}.joblib"
    if not path.exists():
        log.warning("model artifact %s is missing, falling back to the hand-made score", path.name)
        return None
    return rm.load(path)


def score(df: pd.DataFrame, features: pd.DataFrame, with_sitelinks: bool) -> tuple[np.ndarray, str]:
    """Return relevance in [0, 1] for every row and the name of the scorer used.

    Sightseeing categories are scored by the learned model. Cafes and bars were
    absent from the ground truth, so the model cannot rank them; they get the
    tag-based score, capped so that they never outrank real sights.
    """
    manual = manual_popularity(features)
    manual01 = np.clip((manual - 0.3) / 0.7, 0.0, 1.0)
    feature_set = "osm+sitelinks" if with_sitelinks else "osm"
    artifact = _artifact(feature_set)
    if artifact is None:
        return manual01, "manual"
    data = features.copy()
    if with_sitelinks:
        data["sitelinks_log"] = np.log1p(df["sitelinks"].to_numpy(float))
    learned = rm.predict(artifact["model"], data, feature_set)
    is_service = df["category"].isin(SERVICE_CATEGORIES).to_numpy()
    cap = SERVICE_RELEVANCE_CAP * float(learned[~is_service].max()) if (~is_service).any() else 1.0
    return np.where(is_service, manual01 * cap, learned), feature_set
