"""Recommendation use case: candidates from PostGIS -> ranking -> diversified page."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified
from timezonefinder import TimezoneFinder

from .. import diversify as dv
from .. import hours
from ..geo import haversine_m
from ..taxonomy import CATEGORIES
from .config import get_settings
from .ingest import ensure_area, within
from .models import Poi
from .providers import wikimedia
from .schemas import PoiOut, Reason, RecommendRequest, RecommendResponse, Summary

log = logging.getLogger(__name__)
_CAT_CODE = {c: i for i, c in enumerate(CATEGORIES)}
_NO_SUMMARY = {"none": True}


@lru_cache
def _tz_finder() -> TimezoneFinder:
    return TimezoneFinder()


def local_now(lat: float, lon: float) -> datetime:
    """Current time in the time zone of the place (not of the server)."""
    name = _tz_finder().timezone_at(lat=lat, lng=lon)
    return datetime.now(ZoneInfo(name)) if name else datetime.now(UTC)


def poi_out(poi: Poi, lang: str = "uk", now: datetime | None = None) -> PoiOut:
    name = (poi.name_uk if lang == "uk" else poi.name_en) or poi.name
    is_open = hours.is_open(hours.parse(poi.opening_hours), now) if now is not None else None
    summary = (poi.summary or {}).get(lang)
    return PoiOut(
        id=poi.id,
        name=name,
        lat=poi.lat,
        lon=poi.lon,
        category=poi.category,
        subtype=poi.subtype,
        visit_minutes=poi.visit_minutes,
        opening_hours=poi.opening_hours,
        is_open=is_open,
        website=poi.tags.get("website") or poi.tags.get("contact:website"),
        wikidata=poi.wikidata,
        sitelinks=poi.sitelinks,
        summary=Summary(**summary) if summary and not summary.get("none") else None,
    )


def rank(
    pois: list[Poi],
    anchor: tuple[float, float],
    radius_m: float,
    req: RecommendRequest,
    context_categories: list[str],
) -> tuple[list[int], np.ndarray, np.ndarray]:
    """Pure ranking step: returns chosen indices, final scores and distances (m)."""
    settings = get_settings()
    lat = np.array([p.lat for p in pois])
    lon = np.array([p.lon for p in pois])
    dist = haversine_m(anchor[0], anchor[1], lat, lon)
    closeness = np.clip(1.0 - dist / radius_m, 0.0, 1.0)
    relevance = dv.minmax(np.array([p.relevance for p in pois]))
    # explicit preferences: a liked category gets a bonus that lifts even its modest
    # places into view (+2 -> best place of the category rivals the top sights);
    # a disliked one is scaled down (-1 -> x0.25) but never hidden completely
    pref = np.array([req.preferences.get(p.category, 0.0) for p in pois])
    relevance = np.where(
        pref >= 0, relevance + 0.35 * pref * (0.5 + relevance), relevance * (1.0 + 0.75 * pref)
    )
    score = (1.0 - settings.distance_weight) * dv.minmax(relevance) + settings.distance_weight * closeness

    pool = np.argsort(-score, kind="stable")[: settings.pool_size]
    cats = np.array([_CAT_CODE[pois[i].category] for i in pool])
    subs = np.array([hash(pois[i].subtype) for i in pool])
    pool_score = score[pool]
    if req.method == "top_k":
        pick = dv.top_k(pool_score, req.limit)
    elif req.method == "round_robin":
        pick = dv.round_robin(pool_score, cats, req.limit)
    elif req.method == "mmr":
        pick = dv.mmr(
            pool_score, dv.category_similarity(cats, subs), req.limit, 1.0 - settings.diversity_lambda / 2
        )
    else:
        weights = {_CAT_CODE[c]: 1.0 + max(req.preferences.get(c, 0.0), -0.9) for c in CATEGORIES}
        context = [_CAT_CODE[c] for c in context_categories if c in _CAT_CODE]
        pick = dv.xquad(pool_score, cats, req.limit, settings.diversity_lambda, weights, context)
    return [int(pool[i]) for i in pick], score, dist


def reasons_for(
    poi: Poi, distance_m: float, is_top: bool, new_category: bool, preferred: bool, is_open: bool | None
):
    out: list[Reason] = []
    if poi.sitelinks >= 5:
        out.append(Reason(code="wiki_languages", value=poi.sitelinks))
    elif poi.wikidata or poi.tags.get("wikipedia"):
        out.append(Reason(code="has_article"))
    if is_top:
        out.append(Reason(code="top_rated"))
    if distance_m <= 600:
        out.append(Reason(code="close", value=round(distance_m, -1)))
    if new_category:
        out.append(Reason(code="new_category"))
    if preferred:
        out.append(Reason(code="preference"))
    if is_open:
        out.append(Reason(code="open_now"))
    return out[:3]


async def enrich_summaries(session: AsyncSession, pois: list[Poi], lang: str) -> None:
    """Fill ``poi.summary[lang]`` for places that have a Wikipedia article (cached forever)."""
    todo = [p for p in pois if lang not in (p.summary or {}) and (p.wikidata or p.tags.get("wikipedia"))]
    if not todo:
        return
    try:
        async with asyncio.timeout(6):
            titles: dict[str, tuple[str, str]] = {}  # poi id -> (lang, title)
            need_lookup = []
            for p in todo:
                tag = p.tags.get("wikipedia", "")
                if tag.startswith(f"{lang}:"):
                    titles[p.id] = (lang, tag.split(":", 1)[1])
                elif p.wikidata:
                    need_lookup.append(p)
                elif ":" in tag:
                    titles[p.id] = tuple(tag.split(":", 1))  # type: ignore[assignment]
            if need_lookup:
                found = await wikimedia.titles_for([p.wikidata for p in need_lookup], list({lang, "en"}))
                for p in need_lookup:
                    links = found.get(p.wikidata, {})
                    tag = p.tags.get("wikipedia", "")
                    if lang in links:
                        titles[p.id] = (lang, links[lang])
                    elif "en" in links:
                        titles[p.id] = ("en", links["en"])
                    elif ":" in tag:
                        titles[p.id] = tuple(tag.split(":", 1))  # type: ignore[assignment]
            by_lang: dict[str, list[str]] = {}
            for src_lang, title in titles.values():
                by_lang.setdefault(src_lang, []).append(title)
            fetched = dict(
                zip(
                    by_lang,
                    await asyncio.gather(*(wikimedia.summaries(k, v) for k, v in by_lang.items())),
                    strict=True,
                )
            )
    except (TimeoutError, Exception):  # enrichment is optional: never fail the request because of it
        log.info("summary enrichment skipped", exc_info=True)
        return
    for p in todo:
        src = titles.get(p.id)
        data = fetched.get(src[0], {}).get(src[1]) if src else None
        p.summary = {**(p.summary or {}), lang: {**data, "lang": src[0]} if data else _NO_SUMMARY}
        flag_modified(p, "summary")
    await session.commit()


async def recommend(session: AsyncSession, req: RecommendRequest) -> RecommendResponse:
    radius_m = req.radius_km * 1000.0
    area = await ensure_area(session, req.lat, req.lon, radius_m)

    stmt = select(Poi).where(within(req.lat, req.lon, radius_m))
    if req.categories:
        stmt = stmt.where(Poi.category.in_(req.categories))
    hidden = set(req.exclude_ids) | set(req.selected_ids)
    pois = [p for p in (await session.scalars(stmt)).all() if p.id not in hidden]

    now = local_now(req.lat, req.lon)
    if req.open_only:
        pois = [p for p in pois if hours.is_open(hours.parse(p.opening_hours), now) is not False]
    stale = area.source == "overpass" and area.fetched_at < datetime.now(UTC) - timedelta(
        days=get_settings().area_ttl_days
    )
    status = "stale" if stale else "fresh"
    model = pois[0].relevance_model if pois else "none"
    if not pois:
        return RecommendResponse(
            items=[], total_candidates=0, model=model, data_status=status, enrichment=area.wiki_status
        )

    context_categories: list[str] = []
    if req.selected_ids:
        context_categories = list(
            (await session.scalars(select(Poi.category).where(Poi.id.in_(req.selected_ids)))).all()
        )
    anchor = (req.anchor.lat, req.anchor.lon) if req.anchor else (req.lat, req.lon)
    chosen, score, dist = rank(pois, anchor, radius_m, req, context_categories)
    picked = [pois[i] for i in chosen]
    await enrich_summaries(session, picked, req.lang)

    top_cut = np.quantile([p.relevance for p in pois], 0.98)
    seen = set(context_categories)
    items: list[PoiOut] = []
    for i, poi in zip(chosen, picked, strict=True):
        out = poi_out(poi, req.lang, now)
        out.score = round(float(score[i]), 4)
        out.distance_m = round(float(dist[i]), 1)
        out.reasons = reasons_for(
            poi,
            float(dist[i]),
            is_top=poi.relevance >= top_cut,
            new_category=bool(req.selected_ids) and poi.category not in seen,
            preferred=req.preferences.get(poi.category, 0.0) > 0,
            is_open=out.is_open,
        )
        items.append(out)
    return RecommendResponse(
        items=items, total_candidates=len(pois), model=model, data_status=status, enrichment=area.wiki_status
    )
