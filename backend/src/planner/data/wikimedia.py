"""Cached access to Wikipedia / Wikidata signals used as popularity evidence.

Research-time client (synchronous, rate-limited, fully cached on disk) so that
every experiment can be re-run offline and gives identical numbers.
"""

from __future__ import annotations

import time
from urllib.parse import quote, unquote

import httpx

from .kvcache import KVCache
from .paths import CACHE_DIR

USER_AGENT = "planner-thesis-research/0.1 (academic project; contact via repository)"
PAGEVIEW_YEAR = 2025
_MISSING = {"missing": True}
# Seconds between requests per host; grows automatically when a host answers 429.
_HOST_INTERVAL_S: dict[str, float] = {"www.wikidata.org": 1.0, "wikimedia.org": 0.1}


class Wikimedia:
    def __init__(self) -> None:
        self.cache = KVCache(CACHE_DIR / "wikimedia.sqlite")
        self.http = httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=30)
        self._last: dict[str, float] = {}

    def _get(self, url: str, params: dict | None = None) -> httpx.Response:
        """GET with a per-host pace that adapts to 429 responses (Retry-After honoured)."""
        host = httpx.URL(url).host
        interval = _HOST_INTERVAL_S.get(host, 1.0)
        for attempt in range(8):
            wait = interval - (time.monotonic() - self._last.get(host, 0.0))
            if wait > 0:
                time.sleep(wait)
            self._last[host] = time.monotonic()
            try:
                resp = self.http.get(url, params=params)
            except httpx.HTTPError:
                time.sleep(min(2**attempt, 60))
                continue
            if resp.status_code == 429 or resp.status_code >= 500:
                retry_after = resp.headers.get("retry-after", "")
                pause = float(retry_after) if retry_after.isdigit() else 0.0
                time.sleep(max(pause, min(2**attempt, 60)))
                _HOST_INTERVAL_S[host] = min(interval * 1.5, 5.0)
                interval = _HOST_INTERVAL_S[host]
                continue
            return resp
        raise RuntimeError(f"request failed after retries: {url}")

    # -- Wikipedia titles -> Wikidata ids ---------------------------------
    def titles_to_qids(self, titles: list[str], lang: str = "en") -> dict[str, str | None]:
        """Resolve article titles (redirects followed) to Wikidata QIDs."""
        clean = {t: unquote(t).replace("_", " ").strip() for t in titles}
        keys = {t: f"qid:{lang}:{c}" for t, c in clean.items()}
        cached = self.cache.get_many(list(keys.values()))
        todo = sorted({c for t, c in clean.items() if keys[t] not in cached})
        for i in range(0, len(todo), 50):
            chunk = todo[i : i + 50]
            data = self._get(
                f"https://{lang}.wikipedia.org/w/api.php",
                {"action": "query", "format": "json", "formatversion": "2", "redirects": "1",
                 "prop": "pageprops", "ppprop": "wikibase_item", "titles": "|".join(chunk)},
            ).json()["query"]
            alias = {n["from"]: n["to"] for n in data.get("normalized", [])}
            redir = {r["from"]: r["to"] for r in data.get("redirects", [])}
            by_title = {p["title"]: p.get("pageprops", {}).get("wikibase_item") for p in data.get("pages", [])}
            fresh = {}
            for title in chunk:
                final = alias.get(title, title)
                final = redir.get(final, final)
                fresh[f"qid:{lang}:{title}"] = {"qid": by_title.get(final)}
            self.cache.set_many(fresh)
            cached.update(fresh)
        return {t: cached[keys[t]]["qid"] for t in titles}

    # -- Wikidata entities --------------------------------------------------
    def entities(self, qids: list[str]) -> dict[str, dict]:
        """For each QID: number of sitelinks and titles of selected wikis."""
        qids = sorted(set(qids))
        cached = self.cache.get_many([f"ent:{q}" for q in qids])
        todo = [q for q in qids if f"ent:{q}" not in cached]
        for i in range(0, len(todo), 50):
            chunk = todo[i : i + 50]
            data = self._get(
                "https://www.wikidata.org/w/api.php",
                {"action": "wbgetentities", "format": "json", "props": "sitelinks", "ids": "|".join(chunk)},
            ).json().get("entities", {})
            fresh = {}
            for q in chunk:
                ent = data.get(q)
                if not ent or "missing" in ent:
                    fresh[f"ent:{q}"] = _MISSING
                    continue
                links = ent.get("sitelinks", {})
                wikis = {k: v["title"] for k, v in links.items() if k.endswith("wiki") and k not in ("commonswiki", "specieswiki", "metawiki")}
                fresh[f"ent:{q}"] = {"sitelinks": len(wikis), "enwiki": wikis.get("enwiki"), "wikis": dict(list(wikis.items())[:400])}
            # redirects: wbgetentities returns the target id, keep the request id resolvable
            for q in chunk:
                fresh.setdefault(f"ent:{q}", _MISSING)
            self.cache.set_many(fresh)
            cached.update(fresh)
        return {q: cached[f"ent:{q}"] for q in qids}

    # -- Pageviews ----------------------------------------------------------
    def pageviews(self, project: str, title: str, year: int = PAGEVIEW_YEAR) -> int:
        """Total human pageviews of an article in ``year`` (0 when unknown)."""
        key = f"pv:{year}:{project}:{title}"
        hit = self.cache.get(key)
        if hit is not None:
            return int(hit["views"])
        url = (
            "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/"
            f"{project}/all-access/user/{quote(title.replace(' ', '_'), safe='')}/monthly/{year}010100/{year}123100"
        )
        resp = self._get(url)
        views = sum(i["views"] for i in resp.json().get("items", [])) if resp.status_code == 200 else 0
        self.cache.set_many({key: {"views": views}})
        return views
