"""Step 2: build the per-city candidate tables used by all experiments.

For every city: deduplicated classified OSM POIs + features + Wikidata/Wikipedia
signals + ground truth from Flickr (visited or not, number of distinct visitors).

Run: ``uv run python -m planner.experiments.dataset``
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
from tqdm import tqdm

from ..data.flickr import CITIES, poi_popularity
from ..data.paths import PROCESSED_DIR
from ..data.wikimedia import Wikimedia
from ..osm.dedupe import dedupe
from ..ranking.features import density_centre, osm_features


def _wiki_signals(df: pd.DataFrame, wiki: Wikimedia) -> pd.DataFrame:
    tags = [json.loads(t) for t in df["tags"]]
    qids = [t.get("wikidata", "").split(";")[0].strip() for t in tags]
    valid = [q for q in qids if q.startswith("Q") and q[1:].isdigit()]
    ents = wiki.entities(valid)
    sitelinks = np.zeros(len(df))
    views = np.zeros(len(df))
    for i, (q, t) in enumerate(tqdm(list(zip(qids, tags)), desc="pageviews", leave=False)):
        ent = ents.get(q) or {}
        sitelinks[i] = ent.get("sitelinks", 0)
        seen: set[tuple[str, str]] = set()
        if ent.get("enwiki"):
            seen.add(("en", ent["enwiki"]))
        local = t.get("wikipedia", "")
        if ":" in local:
            lang, title = local.split(":", 1)
            if lang.isalpha() and len(lang) <= 3:
                seen.add((lang, title))
        views[i] = sum(wiki.pageviews(f"{lang}.wikipedia", title) for lang, title in seen)
    return pd.DataFrame({"qid": qids, "sitelinks": sitelinks, "pageviews": views}, index=df.index)


def build_city(city: str, wiki: Wikimedia, matches: pd.DataFrame) -> pd.DataFrame:
    raw = dedupe(pd.read_parquet(PROCESSED_DIR / f"osm_{city}.parquet"))
    centre = density_centre(raw)
    df = raw[raw["category"].notna()].reset_index(drop=True)
    feats = osm_features(df, centre)
    wiki_df = _wiki_signals(df, wiki)
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
    wiki = Wikimedia()
    matches = pd.read_parquet(PROCESSED_DIR / "flickr_osm_matches.parquet")
    for city in CITIES:
        src, dst = PROCESSED_DIR / f"osm_{city}.parquet", PROCESSED_DIR / f"candidates_{city}.parquet"
        if not src.exists() or dst.exists() or city not in set(matches["city"]):
            continue
        df = build_city(city, wiki, matches)
        df.to_parquet(dst, index=False)
        print(f"{city}: {len(df)} candidates, {int(df['label'].sum())} visited by Flickr users, "
              f"{int((df['sitelinks'] > 0).sum())} with Wikidata entry")


def load_candidates(cities: list[str] | None = None) -> pd.DataFrame:
    frames = [
        pd.read_parquet(PROCESSED_DIR / f"candidates_{c}.parquet")
        for c in (cities or list(CITIES))
        if (PROCESSED_DIR / f"candidates_{c}.parquet").exists()
    ]
    return pd.concat(frames, ignore_index=True)


if __name__ == "__main__":
    main()
