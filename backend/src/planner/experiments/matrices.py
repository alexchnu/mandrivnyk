"""Step 3: walking time/distance matrices between Flickr POIs of every city.

Run: ``uv run python -m planner.experiments.matrices``
"""

from __future__ import annotations

import numpy as np

from ..data.flickr import CITIES, load_pois
from ..data.paths import PROCESSED_DIR
from ..geo import distance_matrix_m
from ..routing.osrm import table


def load_matrix(city: str) -> dict[str, np.ndarray]:
    data = np.load(PROCESSED_DIR / f"walk_{city}.npz")
    return {k: data[k] for k in data.files}


def main() -> None:
    for city in CITIES:
        dst = PROCESSED_DIR / f"walk_{city}.npz"
        if dst.exists():
            continue
        pois = load_pois(city)
        duration, distance = table(pois["lat"], pois["lon"])
        crow = distance_matrix_m(pois["lat"], pois["lon"])
        np.savez_compressed(
            dst, flickr_id=pois["flickr_id"].to_numpy(), duration_s=duration, distance_m=distance, crow_m=crow
        )
        off = ~np.eye(len(pois), dtype=bool)
        detour = np.median(distance[off] / np.maximum(crow[off], 1.0))
        print(
            f"{city}: {len(pois)} POIs, median walk {np.median(duration[off]) / 60:.0f} min, "
            f"median detour factor {detour:.2f}"
        )


if __name__ == "__main__":
    main()
