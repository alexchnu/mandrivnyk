"""Step 0: cut city-level POI tables out of the regional OSM extracts.

Run: ``uv run python -m planner.experiments.build_extracts``
"""

from __future__ import annotations

import time
from collections import defaultdict

from ..data.flickr import CITIES, load_pois
from ..data.paths import OSM_DIR, PROCESSED_DIR
from ..geo import BBox
from ..osm.extract import extract_pois

MARGIN_M = 3000.0


def main() -> None:
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    by_pbf: dict[str, dict[str, BBox]] = defaultdict(dict)
    for key, spec in CITIES.items():
        if (PROCESSED_DIR / f"osm_{key}.parquet").exists():
            continue
        pois = load_pois(key)
        by_pbf[spec.pbf][key] = BBox.around(pois["lat"], pois["lon"], MARGIN_M)
    for pbf, boxes in by_pbf.items():
        path = OSM_DIR / f"{pbf}-latest.osm.pbf"
        if not path.exists():
            print(f"skip {pbf}: file not downloaded yet")
            continue
        t0 = time.time()
        try:
            frames = extract_pois(path, boxes)
        except RuntimeError as exc:  # truncated file: download still in progress
            print(f"skip {pbf}: {exc}")
            continue
        for key, df in frames.items():
            df.to_parquet(PROCESSED_DIR / f"osm_{key}.parquet", index=False)
            print(f"{key}: {len(df)} named objects, {df['category'].notna().sum()} classified "
                  f"({time.time() - t0:.0f}s)")


if __name__ == "__main__":
    main()
