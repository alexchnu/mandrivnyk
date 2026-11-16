"""Feature engineering for POI significance models.

Two feature groups are produced:

* ``OSM_FEATURES`` - computed from OpenStreetMap alone (tags + spatial context);
  available for any city without extra requests;
* ``WIKI_FEATURES`` - external evidence from Wikidata / Wikipedia.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

from ..taxonomy import CATEGORIES

TAG_FLAGS: dict[str, tuple[str, ...]] = {
    "has_wikidata": ("wikidata",),
    "has_wikipedia": ("wikipedia",),
    "has_website": ("website", "contact:website"),
    "has_opening_hours": ("opening_hours",),
    "has_description": ("description",),
    "has_image": ("image", "wikimedia_commons"),
    "has_phone": ("phone", "contact:phone"),
    "has_name_en": ("name:en",),
    "has_heritage": ("heritage", "heritage:operator"),
    "has_fee": ("fee",),
    "has_wheelchair": ("wheelchair",),
    "has_start_date": ("start_date",),
    "has_author": ("architect", "artist_name"),
    "has_address": ("addr:street", "addr:housenumber"),
    "is_attraction": (),  # filled separately: tourism=attraction
}

CATEGORY_FEATURES = [f"cat_{c}" for c in CATEGORIES]
CONTEXT_FEATURES = ["dist_centre_km", "density_300m", "notable_500m", "food_200m"]
KIND_FEATURES = ["is_node", "is_way", "is_relation"]
OSM_FEATURES = [*TAG_FLAGS, "n_tags_log", *KIND_FEATURES, *CATEGORY_FEATURES, *CONTEXT_FEATURES]
WIKI_FEATURES = ["sitelinks_log", "pageviews_log"]

_EARTH_KM = 6371.0088


def _to_xyz(lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    lat, lon = np.radians(lat), np.radians(lon)
    return _EARTH_KM * np.column_stack([np.cos(lat) * np.cos(lon), np.cos(lat) * np.sin(lon), np.sin(lat)])


def density_centre(df: pd.DataFrame) -> tuple[float, float]:
    """A data-driven city centre: median position of objects with a Wikidata id."""
    notable = df[df["tags"].str.contains('"wikidata"', regex=False)]
    base = notable if len(notable) >= 10 else df
    return float(base["lat"].median()), float(base["lon"].median())


def osm_features(df: pd.DataFrame, centre: tuple[float, float] | None = None) -> pd.DataFrame:
    """Compute ``OSM_FEATURES`` for a table of classified POIs of one city."""
    tags = [json.loads(t) for t in df["tags"]]
    out = pd.DataFrame(index=df.index)
    for name, keys in TAG_FLAGS.items():
        out[name] = [float(any(k in t for k in keys)) for t in tags]
    out["is_attraction"] = [float(t.get("tourism") == "attraction") for t in tags]
    out["n_tags_log"] = np.log1p(df["n_tags"].to_numpy(float))
    kind = df["poi_id"].str[0]
    out["is_node"], out["is_way"], out["is_relation"] = (
        (kind == "n") * 1.0,
        (kind == "w") * 1.0,
        (kind == "r") * 1.0,
    )
    for cat in CATEGORIES:
        out[f"cat_{cat}"] = (df["category"] == cat).to_numpy(float)

    lat, lon = df["lat"].to_numpy(float), df["lon"].to_numpy(float)
    c_lat, c_lon = centre or density_centre(df)
    xyz = _to_xyz(lat, lon)
    out["dist_centre_km"] = np.linalg.norm(xyz - _to_xyz(np.array([c_lat]), np.array([c_lon])), axis=1)
    tree = cKDTree(xyz)
    out["density_300m"] = np.log1p(tree.query_ball_point(xyz, 0.3, return_length=True) - 1)
    notable_mask = out["has_wikidata"].to_numpy() > 0
    out["notable_500m"] = _count_near(xyz, xyz[notable_mask], 0.5) - notable_mask
    food_mask = df["category"].isin(["food", "nightlife"]).to_numpy()
    out["food_200m"] = _count_near(xyz, xyz[food_mask], 0.2) - food_mask
    out["notable_500m"] = np.log1p(out["notable_500m"].clip(lower=0))
    out["food_200m"] = np.log1p(out["food_200m"].clip(lower=0))
    return out[OSM_FEATURES]


def _count_near(points: np.ndarray, targets: np.ndarray, radius_km: float) -> np.ndarray:
    if len(targets) == 0:
        return np.zeros(len(points))
    return cKDTree(targets).query_ball_point(points, radius_km, return_length=True).astype(float)


def manual_popularity(features: pd.DataFrame) -> np.ndarray:
    """Hand-tuned popularity proxy from the coursework (binary tag evidence)."""
    return np.minimum(
        0.3
        + 0.25 * features["has_wikipedia"]
        + 0.15 * features["has_wikidata"]
        + 0.15 * features["has_website"]
        + 0.05 * features["has_description"]
        + 0.10 * features["has_opening_hours"],
        1.0,
    ).to_numpy()


def manual_score(features: pd.DataFrame, radius_km: float) -> np.ndarray:
    """Coursework scoring: 0.4 * popularity + 0.2 * closeness to the centre (no jitter)."""
    closeness = np.clip(1.0 - features["dist_centre_km"].to_numpy() / radius_km, 0.0, 1.0)
    return 0.4 * manual_popularity(features) + 0.2 * closeness
