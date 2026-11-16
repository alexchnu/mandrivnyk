"""Loading points of interest into the database and keeping regions fresh."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta

import pandas as pd
from sqlalchemy import bindparam, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..geo import haversine_m
from ..osm.dedupe import dedupe
from ..ranking.features import density_centre, osm_features
from . import relevance
from .config import get_settings
from .models import Area, Poi
from .providers import overpass
from .providers.http import ProviderError, client

log = logging.getLogger(__name__)
_locks: dict[tuple[int, int], asyncio.Lock] = {}
_background: set[asyncio.Task] = set()


def point(lat: float, lon: float):
    """SQL expression of a geography point."""
    return func.ST_GeogFromText(f"SRID=4326;POINT({lon:.7f} {lat:.7f})")


def within(lat: float, lon: float, radius_m: float):
    return func.ST_DWithin(Poi.geom, point(lat, lon), radius_m)


async def find_area(
    session: AsyncSession, lat: float, lon: float, radius_m: float, fresh_only: bool
) -> Area | None:
    """The most recent loaded region that fully contains the requested circle."""
    areas = (await session.scalars(select(Area).order_by(Area.fetched_at.desc()))).all()
    deadline = datetime.now(UTC) - timedelta(days=get_settings().area_ttl_days)
    for area in areas:
        if fresh_only and area.source == "overpass" and area.fetched_at < deadline:
            continue
        if float(haversine_m(lat, lon, area.lat, area.lon)) + radius_m <= area.radius_m:
            return area
    return None


async def upsert_rows(session: AsyncSession, frame: pd.DataFrame, area_id: int) -> int:
    """Insert or refresh classified POIs; Wikipedia evidence already stored is kept."""
    frame = frame[frame["category"].notna()]
    values = []
    for row in frame.itertuples():
        tags = json.loads(row.tags)
        wikidata = (tags.get("wikidata") or "").split(";")[0].strip() or None
        values.append(
            {
                "id": row.poi_id,
                "name": row.name[:300],
                "name_en": (tags.get("name:en") or None),
                "name_uk": (tags.get("name:uk") or None),
                "lat": row.lat,
                "lon": row.lon,
                "geom": f"SRID=4326;POINT({row.lon:.7f} {row.lat:.7f})",
                "category": row.category,
                "subtype": row.subtype,
                "visit_minutes": int(row.visit_minutes),
                "n_tags": int(row.n_tags),
                "tags": tags,
                "opening_hours": tags.get("opening_hours"),
                "wikidata": wikidata if wikidata and wikidata[:1] == "Q" else None,
                "area_id": area_id,
            }  # fmt: skip
        )
    refreshed = ("name", "name_en", "name_uk", "lat", "lon", "geom", "category", "subtype", "visit_minutes",
                 "n_tags", "tags", "opening_hours", "wikidata", "area_id")  # fmt: skip
    for start in range(0, len(values), 500):
        stmt = insert(Poi).values(values[start : start + 500])
        stmt = stmt.on_conflict_do_update(
            index_elements=[Poi.id],
            set_={c: stmt.excluded[c] for c in refreshed} | {"updated_at": func.now()},
        )
        await session.execute(stmt)
    return len(values)


async def rescore_area(session: AsyncSession, area: Area) -> str:
    """Recompute model relevance for every POI inside the region."""
    rows = (
        await session.execute(
            select(
                Poi.id,
                Poi.name,
                Poi.lat,
                Poi.lon,
                Poi.category,
                Poi.n_tags,
                Poi.tags,
                Poi.sitelinks,
                Poi.wiki_known,
                Poi.wikidata,
            ).where(within(area.lat, area.lon, area.radius_m))  # fmt: skip
        )
    ).all()
    if not rows:
        return "none"
    df = pd.DataFrame(rows, columns=["poi_id", "name", "lat", "lon", "category", "n_tags", "tags", "sitelinks",
                                     "wiki_known", "wikidata"])  # fmt: skip
    df["tags"] = df["tags"].map(lambda t: json.dumps(t, ensure_ascii=False))
    features = osm_features(df, (area.centre_lat, area.centre_lon))
    # sitelinks are usable once every POI that has a Wikidata id has been looked up
    complete = bool((df["wiki_known"] | df["wikidata"].isna()).all())
    scores, model_name = relevance.score(df, features, with_sitelinks=complete)
    table = Poi.__table__
    stmt = (
        update(table)
        .where(table.c.id == bindparam("b_id"))
        .values(relevance=bindparam("b_rel"), relevance_model=model_name)
    )
    params = [{"b_id": pid, "b_rel": float(s)} for pid, s in zip(df["poi_id"], scores, strict=True)]
    for start in range(0, len(params), 1000):
        await session.execute(stmt, params[start : start + 1000])
    return model_name


async def ingest_rows(
    session: AsyncSession,
    rows: list[dict],
    lat: float,
    lon: float,
    radius_m: float,
    source: str,
    sitelinks: dict[str, int] | None = None,
) -> Area:
    """Store a freshly downloaded region and score it. ``sitelinks`` maps QID -> count."""
    frame = dedupe(pd.DataFrame(rows)) if rows else pd.DataFrame(columns=["poi_id", "category"])
    classified = frame[frame["category"].notna()] if len(frame) else frame
    centre = density_centre(frame) if len(frame) else (lat, lon)
    area = Area(lat=lat, lon=lon, radius_m=radius_m, centre_lat=centre[0], centre_lon=centre[1], source=source,
                poi_count=len(classified), wiki_status="done" if sitelinks is not None else "pending")  # fmt: skip
    session.add(area)
    await session.flush()
    if len(classified):
        await upsert_rows(session, classified, area.id)
        if sitelinks is not None:
            await apply_sitelinks(session, area, sitelinks, mark_all=True)
        else:
            # a POI without a Wikidata id has, by definition, zero sitelinks
            await session.execute(
                update(Poi).where(Poi.area_id == area.id, Poi.wikidata.is_(None)).values(wiki_known=True)
            )
        await rescore_area(session, area)
    await session.commit()
    return area


async def apply_sitelinks(session: AsyncSession, area: Area, counts: dict[str, int], mark_all: bool) -> None:
    table = Poi.__table__
    if counts:
        stmt = (
            update(table)
            .where(table.c.wikidata == bindparam("b_qid"))
            .values(sitelinks=bindparam("b_n"), wiki_known=True)
        )
        await session.execute(stmt, [{"b_qid": q, "b_n": int(n)} for q, n in counts.items()])
    if mark_all:
        await session.execute(
            update(Poi).where(within(area.lat, area.lon, area.radius_m)).values(wiki_known=True)
        )


async def fetch_sitelink_counts(qids: list[str], pause_s: float = 1.5) -> dict[str, int]:
    """Number of Wikipedia language editions per Wikidata item (batched, paced)."""
    out: dict[str, int] = {}
    for start in range(0, len(qids), 50):
        chunk = qids[start : start + 50]
        resp = await client().get(
            "https://www.wikidata.org/w/api.php",
            params={
                "action": "wbgetentities",
                "format": "json",
                "props": "sitelinks",
                "ids": "|".join(chunk),
            },
        )
        if resp.status_code != 200:
            raise ProviderError(f"Wikidata returned HTTP {resp.status_code}")
        for qid, ent in resp.json().get("entities", {}).items():
            links = ent.get("sitelinks", {}) if isinstance(ent, dict) else {}
            out[qid] = sum(
                1 for site in links if site.endswith("wiki") and site not in ("commonswiki", "specieswiki")
            )
        for qid in chunk:
            out.setdefault(qid, 0)
        await asyncio.sleep(pause_s)
    return out


async def enrich_area(area_id: int) -> None:
    """Background job: fetch Wikidata evidence for a region and upgrade its relevance."""
    from .db import session_factory

    try:
        async with session_factory()() as session:
            area = await session.get(Area, area_id)
            if area is None or area.wiki_status == "done":
                return
            qids = (
                await session.scalars(
                    select(Poi.wikidata)
                    .where(
                        within(area.lat, area.lon, area.radius_m),
                        Poi.wikidata.is_not(None),
                        Poi.wiki_known.is_(False),
                    )
                    .distinct()  # fmt: skip
                )
            ).all()
            counts = await fetch_sitelink_counts(list(qids))
            await apply_sitelinks(session, area, counts, mark_all=True)
            await rescore_area(session, area)
            area.wiki_status = "done"
            await session.commit()
            log.info("area %s enriched with %s Wikidata items", area_id, len(counts))
    except Exception:  # a failed enrichment must never break request handling
        log.exception("enrichment of area %s failed; the OSM-only model stays in use", area_id)


def schedule_enrichment(area_id: int) -> None:
    task = asyncio.get_running_loop().create_task(enrich_area(area_id))
    _background.add(task)
    task.add_done_callback(_background.discard)


async def ensure_area(session: AsyncSession, lat: float, lon: float, radius_m: float) -> Area:
    """Make sure POIs around the point are loaded; download them when needed."""
    area = await find_area(session, lat, lon, radius_m, fresh_only=True)
    if area is not None:
        return area
    key = (round(lat * 50), round(lon * 50))  # ~2 km grid: one download per neighbourhood at a time
    lock = _locks.setdefault(key, asyncio.Lock())
    async with lock:
        area = await find_area(session, lat, lon, radius_m, fresh_only=True)
        if area is not None:
            return area
        fetch_radius = max(radius_m + 1000.0, get_settings().area_radius_km * 1000.0)
        try:
            rows = await overpass.fetch_rows(lat, lon, fetch_radius)
        except ProviderError:
            stale = await find_area(session, lat, lon, radius_m, fresh_only=False)
            if stale is not None:
                log.warning("serving stale area %s: map data service is down", stale.id)
                return stale
            raise
        area = await ingest_rows(session, rows, lat, lon, fetch_radius, "overpass")
        schedule_enrichment(area.id)
        return area
