"""Step 2: build the per-city candidate tables used by all experiments.

For every city: deduplicated classified OSM POIs + features + Wikidata/Wikipedia
signals + ground truth from Flickr (visited or not, number of distinct visitors).

Run: ``uv run python -m planner.experiments.dataset``
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from ..data import wikidumps
from ..data.flickr import CITIES, poi_popularity
from ..data.paths import PROCESSED_DIR
from ..osm.dedupe import dedupe
from ..ranking.features import density_centre, osm_features
from .wiki_signals import parse_qid, parse_wikipedia_tag


def _wiki_signals(
    df: pd.DataFrame, signals: pd.DataFrame, title_index: dict[tuple[str, str], int]
) -> pd.DataFrame:
    """Attach Wikidata sitelinks and Wikipedia pageviews (all languages, one month)."""
    items: list[int | None] = []
    for raw in df["tags"]:
        tags = json.loads(raw)
        item = parse_qid(tags.get("wikidata"))
        if item is None:
            page = parse_wikipedia_tag(tags.get("wikipedia"))
            item = title_index.get(page) if page else None
        items.append(item)
    out = pd.DataFrame({"item": pd.array(items, dtype="Int64")}, index=df.index)
    out = out.join(signals.set_index("item")[["sitelinks", "pageviews", "pageviews_en"]], on="item")
    out[["sitelinks", "pageviews", "pageviews_en"]] = out[["sitelinks", "pageviews", "pageviews_en"]].fillna(
        0.0
    )
    out["qid"] = ["" if pd.isna(i) else f"Q{i}" for i in out["item"]]
    return out[["qid", "sitelinks", "pageviews", "pageviews_en"]]


def build_city(city: str, matches: pd.DataFrame, signals: pd.DataFrame, title_index: dict) -> pd.DataFrame:
    raw = dedupe(pd.read_parquet(PROCESSED_DIR / f"osm_{city}.parquet"))
    centre = density_centre(raw)
    df = raw[raw["category"].notna()].reset_index(drop=True)
    feats = osm_features(df, centre)
    wiki_df = _wiki_signals(df, signals, title_index)
    feats["sitelinks_log"] = np.log1p(wiki_df["sitelinks"])
    feats["pageviews_log"] = np.log1p(wiki_df["pageviews"])

    m = matches[(matches["city"] == city) & matches["poi_id"].notna()]
    pop = poi_popularity(city).merge(m[["flickr_id", "poi_id"]], on="flickr_id")
    pop = pop.groupby("poi_id", as_index=False).agg(
        flickr_id=("flickr_id", "first"), flickr_users=("users", "sum"), flickr_sequences=("sequences", "sum")
    )
    out = pd.concat([df, wiki_df, feats], axis=1).merge(pop, on="poi_id", how="left")
    out["flickr_users"] = out["flickr_users"].fillna(0)
    out["flickr_sequences"] = out["flickr_sequences"].fillna(0)
    out["label"] = out["flickr_id"].notna().astype(int)
    out.insert(0, "city", city)
    out.attrs["centre"] = centre
    return out


def main() -> None:
    matches = pd.read_parquet(PROCESSED_DIR / "flickr_osm_matches.parquet")
    signals = wikidumps.item_signals()
    links = pd.read_parquet(wikidumps.SITELINKS_TABLE)
    title_index = {(site, title): int(item) for item, site, title in links.itertuples(index=False)}
    for city in CITIES:
        src, dst = PROCESSED_DIR / f"osm_{city}.parquet", PROCESSED_DIR / f"candidates_{city}.parquet"
        if not src.exists() or city not in set(matches["city"]):
            continue
        df = build_city(city, matches, signals, title_index)
        df.to_parquet(dst, index=False)
        print(
            f"{city}: {len(df)} candidates, {int(df['label'].sum())} visited by Flickr users, "
            f"{int((df['sitelinks'] > 0).sum())} with Wikipedia article, "
            f"{int((df['pageviews'] > 0).sum())} with pageviews"
        )


def load_candidates(cities: list[str] | None = None) -> pd.DataFrame:
    frames = [
        pd.read_parquet(PROCESSED_DIR / f"candidates_{c}.parquet")
        for c in (cities or list(CITIES))
        if (PROCESSED_DIR / f"candidates_{c}.parquet").exists()
    ]
    return pd.concat(frames, ignore_index=True)


if __name__ == "__main__":
    main()
