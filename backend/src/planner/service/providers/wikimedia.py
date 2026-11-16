"""Descriptions and photos of places from Wikipedia (batched requests)."""

from __future__ import annotations

import logging

import httpx

from .http import client

log = logging.getLogger(__name__)


async def titles_for(qids: list[str], langs: list[str]) -> dict[str, dict[str, str]]:
    """Wikidata ids -> ``{lang: article title}`` for the requested languages (one request)."""
    if not qids:
        return {}
    try:
        resp = await client().get(
            "https://www.wikidata.org/w/api.php",
            params={
                "action": "wbgetentities",
                "format": "json",
                "props": "sitelinks",
                "ids": "|".join(qids[:50]),
                "sitefilter": "|".join(f"{lang}wiki" for lang in langs),
            },  # fmt: skip
        )
        entities = resp.json().get("entities", {}) if resp.status_code == 200 else {}
    except (httpx.HTTPError, ValueError):
        log.info("wikidata lookup failed")
        return {}
    out: dict[str, dict[str, str]] = {}
    for qid, ent in entities.items():
        links = ent.get("sitelinks", {}) if isinstance(ent, dict) else {}
        out[qid] = {site[:-4]: link["title"] for site, link in links.items() if "title" in link}
    return out


async def summaries(lang: str, titles: list[str], thumb_px: int = 640) -> dict[str, dict]:
    """Intro text, thumbnail and URL for up to 20 articles of one language edition."""
    if not titles:
        return {}
    try:
        resp = await client().get(
            f"https://{lang}.wikipedia.org/w/api.php",
            params={
                "action": "query",
                "format": "json",
                "formatversion": "2",
                "redirects": "1",
                "prop": "extracts|pageimages|info",
                "exintro": "1",
                "explaintext": "1",
                "exsentences": "3",
                "exlimit": "20",
                "piprop": "thumbnail",
                "pithumbsize": str(thumb_px),
                "pilimit": "20",
                "inprop": "url",
                "titles": "|".join(titles[:20]),
            },  # fmt: skip
        )
        query = resp.json().get("query", {}) if resp.status_code == 200 else {}
    except (httpx.HTTPError, ValueError):
        log.info("wikipedia summary lookup failed")
        return {}
    alias: dict[str, str] = {}
    for item in [*query.get("normalized", []), *query.get("redirects", [])]:
        alias[item["from"]] = item["to"]
    pages = {p["title"]: p for p in query.get("pages", []) if not p.get("missing")}
    out: dict[str, dict] = {}
    for title in titles[:20]:
        final = alias.get(title, title)
        final = alias.get(final, final)
        page = pages.get(final)
        if page:
            out[title] = {
                "title": page["title"],
                "extract": (page.get("extract") or "").strip(),
                "image": (page.get("thumbnail") or {}).get("source"),
                "url": page.get("fullurl"),
            }
    return out
