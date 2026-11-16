"""Offline import of regions into the service database.

Unlike the on-demand Overpass path this works without any external service at
request time: POIs come from an OSM extract (``.osm.pbf``) and the Wikipedia
evidence from the Wikidata sitelinks dump, so relevance uses the full model
immediately.

Examples::

    planner-import --pbf ukraine-latest.osm.pbf --place "Чернівці" 48.2921 25.9358
    planner-import --pbf scotland-latest.osm.pbf --place Edinburgh 55.9533 -3.1883 --radius-km 7
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

import pandas as pd

from ..data import wikidumps
from ..geo import BBox, haversine_m
from ..osm.dedupe import dedupe
from ..osm.extract import extract_pois
from . import ingest
from .db import dispose_engine, session_factory


def sitelink_counts(frames: list[pd.DataFrame]) -> dict[str, int]:
    """QID -> number of Wikipedia editions, read from the Wikidata dump."""
    wanted: set[int] = set()
    for frame in frames:
        for raw in frame.loc[frame["category"].notna(), "tags"]:
            qid = (json.loads(raw).get("wikidata") or "").split(";")[0].strip()
            if qid[:1] == "Q" and qid[1:].isdigit():
                wanted.add(int(qid[1:]))
    if not wanted:
        return {}
    links = wikidumps.scan_sitelinks(wanted, set())
    links = links[links["site"].map(wikidumps.is_wikipedia)]
    counts = links.groupby("item")["site"].nunique()
    return {f"Q{item}": int(counts.get(item, 0)) for item in wanted}


async def import_places(pbf: Path, places: list[tuple[str, float, float]], radius_km: float) -> None:
    radius_m = radius_km * 1000.0
    boxes = {name: BBox.around([lat], [lon], radius_m) for name, lat, lon in places}
    print(f"reading {pbf.name} for {len(places)} place(s) ...")
    frames = extract_pois(pbf, boxes)
    prepared: dict[str, pd.DataFrame] = {}
    for name, lat, lon in places:
        frame = dedupe(frames[name])
        inside = haversine_m(lat, lon, frame["lat"].to_numpy(), frame["lon"].to_numpy()) <= radius_m
        prepared[name] = frame[inside].reset_index(drop=True)
    print("reading Wikidata sitelinks ...")
    counts = sitelink_counts(list(prepared.values()))
    async with session_factory()() as session:
        for name, lat, lon in places:
            rows = prepared[name].to_dict("records")
            area = await ingest.ingest_rows(session, rows, lat, lon, radius_m, "import", sitelinks=counts)
            print(f"{name}: {area.poi_count} places imported (area {area.id})")
    await dispose_engine()


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--pbf", type=Path, required=True, help="OSM extract (.osm.pbf)")
    parser.add_argument("--radius-km", type=float, default=7.0)
    parser.add_argument("--place", nargs=3, action="append", metavar=("NAME", "LAT", "LON"), required=True)
    args = parser.parse_args()
    places = [(name, float(lat), float(lon)) for name, lat, lon in args.place]
    asyncio.run(import_places(args.pbf, places, args.radius_km))


if __name__ == "__main__":
    main()
