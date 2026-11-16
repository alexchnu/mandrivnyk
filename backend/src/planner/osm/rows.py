"""Conversion of a raw OSM object into a POI row (shared by PBF and Overpass paths)."""

from __future__ import annotations

import json

from ..taxonomy import RELEVANT_KEYS, classify

# Tags that are kept verbatim for feature engineering and display.
KEPT_TAGS = (
    "name", "name:en", "name:uk", "wikidata", "wikipedia", "website", "contact:website",
    "opening_hours", "description", "image", "wikimedia_commons", "phone", "contact:phone",
    "tourism", "historic", "amenity", "leisure", "natural", "man_made", "shop", "place",
    "building", "railway", "bridge", "sport", "highway", "heritage", "heritage:operator",
    "fee", "wheelchair", "cuisine", "religion", "denomination", "start_date", "operator",
    "architect", "artist_name", "ele", "height", "stars", "addr:street", "addr:housenumber",
)  # fmt: skip


def build_row(kind: str, osm_id: int, lat: float, lon: float, tags: dict[str, str]) -> dict | None:
    """Return a POI row or ``None`` when the object has no name or no relevant tag."""
    name = tags.get("name")
    if not name or not (RELEVANT_KEYS & tags.keys()):
        return None
    rule = classify(tags)
    return {
        "poi_id": f"{kind}{osm_id}",
        "name": name,
        "lat": lat,
        "lon": lon,
        "category": rule.category if rule else None,
        "subtype": (rule.value if rule.value != "*" else "notable") if rule else None,
        "visit_minutes": rule.visit_minutes if rule else None,
        "n_tags": len(tags),
        "tags": json.dumps({k: tags[k] for k in KEPT_TAGS if k in tags}, ensure_ascii=False),
    }
