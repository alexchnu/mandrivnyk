"""Extract named points of interest from an OSM PBF file.

Used offline: for the experiments (reproducible snapshots instead of live
Overpass queries) and to pre-load regions into the service database.
"""

from __future__ import annotations

from pathlib import Path

import osmium
import pandas as pd

from ..geo import BBox
from .rows import build_row


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
        if not hits or (kind, osm_id) in seen:
            return
        row = build_row(kind, osm_id, lat, lon, {t.k: t.v for t in tags})
        if row is None:
            return
        seen.add((kind, osm_id))
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
