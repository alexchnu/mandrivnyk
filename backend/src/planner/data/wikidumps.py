"""Popularity evidence from official Wikimedia dumps (offline, reproducible).

* ``wb_items_per_site`` (Wikidata): for every item, the list of wiki pages that
  describe it -> number of sitelinks and article titles in every language.
* ``pageview_complete`` (monthly): human pageviews of every article.

Bulk dumps are used instead of the live APIs: the APIs throttle anonymous
clients to roughly one request per minute, while the dumps are meant for this.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pandas as pd

from .paths import DATA_ROOT, PROCESSED_DIR

DUMP_DIR = DATA_ROOT / "wikidumps"
SITELINKS_DUMP = DUMP_DIR / "wikidatawiki-latest-wb_items_per_site.sql.gz"
PAGEVIEWS_DUMP = DUMP_DIR / "pageviews-202610-user.bz2"
PAGEVIEWS_MONTH = "2026-10"
SITELINKS_TABLE = PROCESSED_DIR / "wiki_sitelinks.parquet"
PAGEVIEWS_TABLE = PROCESSED_DIR / "wiki_pageviews.parquet"
_NOT_WIKIPEDIA = {
    "commonswiki",
    "specieswiki",
    "metawiki",
    "wikidatawiki",
    "mediawikiwiki",
    "sourceswiki",
    "outreachwiki",
    "incubatorwiki",
    "foundationwiki",
    "wikimaniawiki",
    "wikifunctionswiki",
}


def is_wikipedia(site: str) -> bool:
    return site.endswith("wiki") and site not in _NOT_WIKIPEDIA


def _unescape(text: str) -> str:
    return text.replace("\\'", "'").replace('\\"', '"').replace("\\\\", "\\")


def scan_sitelinks(wanted_qids: set[int], wanted_titles: set[tuple[str, str]]) -> pd.DataFrame:
    """One pass over the sitelinks dump: rows of wanted items and wanted (site, title) pairs."""
    rows: list[tuple[int, str, str]] = []
    proc = subprocess.Popen(["pigz", "-dc", str(SITELINKS_DUMP)], stdout=subprocess.PIPE, bufsize=1 << 20)
    assert proc.stdout is not None
    for raw in proc.stdout:
        if raw[:1] != b"(":
            continue
        # (row_id,item_id,'site','title'),
        first = raw.find(b",")
        second = raw.find(b",", first + 1)
        item = int(raw[first + 1 : second])
        hit = item in wanted_qids
        if not hit and not wanted_titles:
            continue
        third = raw.find(b",", second + 1)
        site = raw[second + 2 : third - 1].decode()
        if not hit and not is_wikipedia(site):
            continue
        title = _unescape(raw[third + 2 : raw.rfind(b"'")].decode("utf-8", "replace"))
        if hit or (site, title) in wanted_titles:
            rows.append((item, site, title))
    proc.wait()
    return pd.DataFrame(rows, columns=["item", "site", "title"]).drop_duplicates()


def build_sitelinks(wanted_qids: set[int], wanted_titles: set[tuple[str, str]]) -> pd.DataFrame:
    """Sitelinks of wanted items; items referenced only by a page title are resolved first."""
    first = scan_sitelinks(wanted_qids, wanted_titles)
    discovered = set(first["item"]) - wanted_qids
    if discovered:
        first = pd.concat([first, scan_sitelinks(discovered, set())]).drop_duplicates()
    first.to_parquet(SITELINKS_TABLE, index=False)
    return first


def build_pageviews(sitelinks: pd.DataFrame, work_dir: Path | None = None) -> pd.DataFrame:
    """Filter the monthly pageview dump down to the articles of wanted items."""
    work_dir = work_dir or DUMP_DIR
    wiki = sitelinks[sitelinks["site"].map(is_wikipedia)].copy()
    wiki["project"] = wiki["site"].str[:-4].str.replace("_", "-") + ".wikipedia"
    wiki["page"] = wiki["title"].str.replace(" ", "_")
    keys = work_dir / "wanted_pages.txt"
    keys.write_text("\n".join(sorted(set(wiki["project"] + " " + wiki["page"]))) + "\n", encoding="utf-8")
    out = work_dir / "pageviews_filtered.tsv"
    script = r'NR==FNR {w[$0]; next} ($1 " " $2) in w {print $1 "\t" $2 "\t" $5}'
    with out.open("wb") as sink:
        bz = subprocess.Popen(["bzcat", str(PAGEVIEWS_DUMP)], stdout=subprocess.PIPE)
        awk = subprocess.Popen(
            ["awk", script, str(keys), "-"], stdin=bz.stdout, stdout=sink, env={"LC_ALL": "C"}
        )
        awk.wait()
        bz.wait()
    views = pd.read_csv(
        out, sep="\t", names=["project", "page", "views"], quoting=3, dtype={"views": "int64"}
    )
    views = views.groupby(["project", "page"], as_index=False)["views"].sum()
    merged = wiki.merge(views, on=["project", "page"], how="left").fillna({"views": 0})
    merged[["item", "site", "title", "views"]].to_parquet(PAGEVIEWS_TABLE, index=False)
    return merged


def item_signals() -> pd.DataFrame:
    """Per Wikidata item: sitelinks count, total and English pageviews, English title."""
    links = pd.read_parquet(SITELINKS_TABLE)
    links = links[links["site"].map(is_wikipedia)]
    out = links.groupby("item").agg(sitelinks=("site", "nunique")).reset_index()
    if PAGEVIEWS_TABLE.exists():
        pv = pd.read_parquet(PAGEVIEWS_TABLE)
        total = pv.groupby("item")["views"].sum().rename("pageviews")
        en = pv[pv["site"] == "enwiki"].groupby("item")["views"].sum().rename("pageviews_en")
        out = out.merge(total, on="item", how="left").merge(en, on="item", how="left")
    else:
        out["pageviews"] = 0.0
        out["pageviews_en"] = 0.0
    en_title = (
        links[links["site"] == "enwiki"].drop_duplicates("item").set_index("item")["title"].rename("enwiki")
    )
    return out.merge(en_title, on="item", how="left").fillna({"pageviews": 0, "pageviews_en": 0})
