"""Step 2a: extract Wikidata/Wikipedia signals for all candidate POIs from dumps.

Run: ``uv run python -m planner.experiments.wiki_signals [sitelinks|pageviews]``
"""

from __future__ import annotations

import json
import sys
import time

import pandas as pd

from ..data import wikidumps as wd
from ..data.flickr import CITIES
from ..data.paths import PROCESSED_DIR
from ..osm.dedupe import dedupe


def parse_qid(value: str | None) -> int | None:
    if not value:
        return None
    first = value.split(";")[0].strip()
    return int(first[1:]) if first[:1] == "Q" and first[1:].isdigit() else None


def parse_wikipedia_tag(value: str | None) -> tuple[str, str] | None:
    """``"de:Stephansdom (Wien)"`` -> ``("dewiki", "Stephansdom (Wien)")``."""
    if not value or ":" not in value:
        return None
    lang, title = value.split(":", 1)
    lang = lang.strip().lower()
    if not (2 <= len(lang) <= 12 and lang.replace("-", "").isalpha()):
        return None
    title = title.replace("_", " ").strip()
    return (lang.replace("-", "_") + "wiki", title[:1].upper() + title[1:]) if title else None


def wanted() -> tuple[set[int], set[tuple[str, str]]]:
    qids: set[int] = set()
    titles: set[tuple[str, str]] = set()
    for city in CITIES:
        path = PROCESSED_DIR / f"osm_{city}.parquet"
        if not path.exists():
            continue
        df = dedupe(pd.read_parquet(path))
        for raw in df.loc[df["category"].notna(), "tags"]:
            tags = json.loads(raw)
            qid = parse_qid(tags.get("wikidata"))
            if qid is not None:
                qids.add(qid)
            else:
                page = parse_wikipedia_tag(tags.get("wikipedia"))
                if page:
                    titles.add(page)
    matches = PROCESSED_DIR / "flickr_osm_matches.parquet"
    if matches.exists():
        qids |= {q for q in (parse_qid(v) for v in pd.read_parquet(matches)["qid"].dropna()) if q is not None}
    return qids, titles


def main() -> None:
    step = sys.argv[1] if len(sys.argv) > 1 else "all"
    t0 = time.time()
    if step in ("sitelinks", "all"):
        qids, titles = wanted()
        print(f"wanted: {len(qids)} items, {len(titles)} pages without item id")
        links = wd.build_sitelinks(qids, titles)
        print(f"sitelinks: {len(links)} rows for {links['item'].nunique()} items ({time.time() - t0:.0f}s)")
    if step in ("pageviews", "all"):
        links = pd.read_parquet(wd.SITELINKS_TABLE)
        views = wd.build_pageviews(links)
        print(
            f"pageviews: {int(views['views'].sum()):,} views over {len(views)} articles ({time.time() - t0:.0f}s)"
        )


if __name__ == "__main__":
    main()
