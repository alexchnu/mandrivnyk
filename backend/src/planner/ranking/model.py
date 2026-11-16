"""Learned POI significance models.

A model estimates the probability that a point of interest is a place tourists
actually visit. It is trained on cities with ground truth (Flickr trajectories)
and applied to any other city, so the features must be city-independent.
"""

from __future__ import annotations

from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .features import OSM_FEATURES, WIKI_FEATURES

FEATURE_SETS: dict[str, list[str]] = {
    "osm": OSM_FEATURES,
    "osm+sitelinks": [*OSM_FEATURES, "sitelinks_log"],
    "osm+wiki": [*OSM_FEATURES, *WIKI_FEATURES],
}
SIGHT_CATEGORIES = ("culture", "history", "landmark", "nature", "religion", "entertainment", "shopping")


def make_model(kind: str, seed: int = 0):
    if kind == "logreg":
        return make_pipeline(
            StandardScaler(),
            LogisticRegression(C=0.3, class_weight="balanced", max_iter=2000, random_state=seed),
        )
    if kind == "lgbm":
        return LGBMClassifier(
            n_estimators=300,
            learning_rate=0.03,
            num_leaves=15,
            min_child_samples=10,
            subsample=0.8,
            subsample_freq=1,
            colsample_bytree=0.8,
            reg_lambda=5.0,
            class_weight="balanced",
            random_state=seed,
            verbose=-1,
            n_jobs=4,
        )
    raise ValueError(kind)


def fit(df: pd.DataFrame, feature_set: str = "osm", kind: str = "lgbm", seed: int = 0):
    cols = FEATURE_SETS[feature_set]
    model = make_model(kind, seed)
    model.fit(df[cols], df["label"].to_numpy())
    return model


def predict(model, df: pd.DataFrame, feature_set: str = "osm") -> np.ndarray:
    return model.predict_proba(df[FEATURE_SETS[feature_set]])[:, 1]


def save(model, path: Path, feature_set: str, kind: str, meta: dict | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"model": model, "feature_set": feature_set, "kind": kind, "meta": meta or {}}, path)


def load(path: Path) -> dict:
    return joblib.load(path)
