"""Extract named points of interest from an OSM PBF file.

Used offline: for the experiments (reproducible snapshots instead of live
Overpass queries) and to pre-load regions into the service database.
"""

from __future__ import annotations

import json
from pathlib import Path

import osmium
import pandas as pd

from ..geo import BBox
from ..taxonomy import RELEVANT_KEYS, classify

# Tags that are kept verbatim for feature engineering and display.
KEPT_TAGS = (
    "name",
    "name:en",
    "name:uk",
    "wikidata",
    "wikipedia",
    "website",
    "contact:website",
    "opening_hours",
    "description",
    "image",
    "wikimedia_commons",
    "phone",
    "contact:phone",
    "tourism",
    "historic",
    "amenity",
    "leisure",
    "natural",
    "man_made",
    "shop",
    "place",
    "building",
    "railway",
    "bridge",
    "sport",
    "highway",
    "heritage",
    "heritage:operator",
    "fee",
    "wheelchair",
    "cuisine",
    "religion",
    "denomination",
    "start_date",
    "operator",
    "architect",
    "artist_name",
    "ele",
    "height",
    "stars",
    "addr:street",
    "addr:housenumber",
)


def _ring_centroid(nodes) -> tuple[float, float] | None:
    lat = lon = 0.0
    n = 0
    for node in nodes:
        if node.location.valid():
            lat += node.location.lat
            lon += node.location.lon
            n += 1
    return (lat / n, lon / n) if n else None


def extract_pois(pbf: Path, bboxes: dict[str, BBox]) -> dict[str, pd.DataFrame]:
    """Scan ``pbf`` once and return one DataFrame of named objects per bounding box."""
    rows: dict[str, list[dict]] = {name: [] for name in bboxes}
    seen: set[tuple[str, int]] = set()

    def emit(kind: str, osm_id: int, lat: float, lon: float, tags) -> None:
        hits = [name for name, box in bboxes.items() if box.contains(lat, lon)]
        if not hits:
            return
        tag_dict = {k: v for k, v in ((t.k, t.v) for t in tags)}
        if not (RELEVANT_KEYS & tag_dict.keys()):
            return
        if (kind, osm_id) in seen:
            return
        seen.add((kind, osm_id))
        rule = classify(tag_dict)
        row = {
            "poi_id": f"{kind}{osm_id}",
            "name": tag_dict["name"],
            "lat": lat,
            "lon": lon,
            "category": rule.category if rule else None,
            "subtype": (rule.value if rule.value != "*" else "notable") if rule else None,
            "visit_minutes": rule.visit_minutes if rule else None,
            "n_tags": len(tag_dict),
            "tags": json.dumps({k: tag_dict[k] for k in KEPT_TAGS if k in tag_dict}, ensure_ascii=False),
        }
        for name in hits:
            rows[name].append(row)

    processor = (
        osmium.FileProcessor(str(pbf))
        .with_locations()
        .with_areas()
        .with_filter(osmium.filter.EmptyTagFilter())
        .with_filter(osmium.filter.KeyFilter("name"))
    )
    for obj in processor:
        if obj.is_node():
            emit("n", obj.id, obj.location.lat, obj.location.lon, obj.tags)
        elif obj.is_area():
            # Areas come from closed ways (even id) and multipolygon relations (odd id).
            kind = "w" if obj.from_way() else "r"
            for ring in obj.outer_rings():
                centre = _ring_centroid(ring)
                if centre:
                    emit(kind, obj.orig_id(), *centre, obj.tags)
                break
        elif obj.is_way() and not obj.is_closed():
            centre = _ring_centroid(obj.nodes)
            if centre:
                emit("w", obj.id, *centre, obj.tags)

    return {name: pd.DataFrame(r) for name, r in rows.items()}
