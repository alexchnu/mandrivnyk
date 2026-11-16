"""Step 1: link Flickr POIs (ground truth of tourist visits) to OSM objects.

Run: ``uv run python -m planner.experiments.match``
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
from rapidfuzz import fuzz

from ..data.flickr import CITIES, load_pois
from ..data.paths import PROCESSED_DIR
from ..data.wikimedia import Wikimedia
from ..geo import haversine_m
from ..osm.dedupe import dedupe, normalise_name

QID_RADIUS_M = 3000.0  # the id is unambiguous, the radius only guards against data errors
SEARCH_RADIUS_M = 600.0
MIN_SIMILARITY = 85.0
_NEVER_FUZZY = {"food", "nightlife", "shopping"}  # a cafe named after a landmark is not the landmark


def _names(row) -> list[str]:
    tags = json.loads(row.tags)
    return [normalise_name(n) for n in {row.name, tags.get("name:en", "")} if n]


def match_city(city: str, wiki: Wikimedia | None = None) -> pd.DataFrame:
    """Two-stage linking: exact Wikidata id first, fuzzy name + distance second."""
    flickr = load_pois(city)
    osm = dedupe(pd.read_parquet(PROCESSED_DIR / f"osm_{city}.parquet"))
    osm_tags = [json.loads(t) for t in osm["tags"]]
    osm_qid = np.array([t.get("wikidata", "") for t in osm_tags])
    osm_names = [_names(r) for r in osm.itertuples()]
    classified = osm["category"].notna().to_numpy()
    category = osm["category"].to_numpy()
    lat, lon = osm["lat"].to_numpy(), osm["lon"].to_numpy()

    qids: dict[str, str | None] = {}
    if CITIES[city].source == "ijcai15":
        qids = (wiki or Wikimedia()).titles_to_qids(flickr["title"].tolist())

    rows = []
    for f in flickr.itertuples():
        dist = haversine_m(f.lat, f.lon, lat, lon)
        qid = qids.get(f.title)
        best, how = None, None
        if qid:
            same = np.flatnonzero((osm_qid == qid) & (dist <= QID_RADIUS_M))
            if len(same):
                best = int(max(same, key=lambda i: (classified[i], -dist[i])))
                how = "wikidata"
        if best is None:
            target = normalise_name(f.name)
            best_key = None
            for i in np.flatnonzero(dist <= SEARCH_RADIUS_M):
                if not (classified[i] or osm_qid[i]) or category[i] in _NEVER_FUZZY:
                    continue
                sim = max(max(fuzz.token_set_ratio(target, n), fuzz.ratio(target, n)) for n in osm_names[i])
                if sim < MIN_SIMILARITY:
                    continue
                key = (
                    round(max(fuzz.ratio(target, n) for n in osm_names[i]) / 10),
                    bool(osm_qid[i]),
                    -dist[i],
                )
                if best_key is None or key > best_key:
                    best, best_key, how = int(i), key, "name"
        hit = best is not None
        rows.append(
            {
                "city": city,
                "flickr_id": f.flickr_id,
                "flickr_name": f.name,
                "theme": f.theme,
                "qid": qid,
                "poi_id": osm["poi_id"].iloc[best] if hit else None,
                "osm_name": osm["name"].iloc[best] if hit else None,
                "osm_category": osm["category"].iloc[best] if hit else None,
                "dist_m": float(dist[best]) if hit else np.nan,
                "method": how,
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    frames = []
    wiki = Wikimedia()
    for city in CITIES:
        if not (PROCESSED_DIR / f"osm_{city}.parquet").exists():
            continue
        m = match_city(city, wiki)
        frames.append(m)
        ok = m["poi_id"].notna()
        print(
            f"{city}: matched {ok.sum()}/{len(m)} (by id {(m['method'] == 'wikidata').sum()}), "
            f"classified {m['osm_category'].notna().sum()}, median dist {m.loc[ok, 'dist_m'].median():.0f} m"
        )
        if (~ok).any():
            print("   unmatched:", "; ".join(m.loc[~ok, "flickr_name"].head(12)))
    if frames:
        pd.concat(frames).to_parquet(PROCESSED_DIR / "flickr_osm_matches.parquet", index=False)


if __name__ == "__main__":
    main()
