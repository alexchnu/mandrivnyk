import httpx
import pytest
from sqlalchemy import func, select

from planner.service import ingest
from planner.service.models import Area, Poi
from planner.service.providers import overpass
from planner.service.providers.http import ProviderError

from .conftest import CENTRE, SAMPLE_ELEMENTS


def test_query_covers_taxonomy():
    query = overpass.build_query(48.29, 25.93, 3000)
    assert '"tourism"~"^(museum|' in query and "around:3000,48.290000,25.930000" in query
    assert query.strip().endswith("out center tags;")


def test_parse_elements_skips_unusable():
    rows = overpass.parse_elements([*SAMPLE_ELEMENTS, {"type": "way", "id": 99, "tags": {"name": "No centre"}},
                                    {"type": "node", "id": 98, "lat": 1, "lon": 1, "tags": {"tourism": "museum"}}])  # fmt: skip
    ids = {r["poi_id"] for r in rows}
    assert "w18" in ids and "n1" in ids and "w99" not in ids and "n98" not in ids
    assert "n17" not in ids  # no tourism-related tag at all: dropped before classification


async def test_ingest_stores_classified_and_scores(session, city):
    assert (
        await session.scalar(select(func.count()).select_from(Poi)) == 17
    )  # the unclassified office is dropped
    palace = await session.get(Poi, "w18")
    cafe = await session.get(Poi, "n8")
    monument = await session.get(Poi, "n7")
    assert palace.category == "history" and palace.sitelinks == 55 and palace.wiki_known
    assert 0.0 <= cafe.relevance <= palace.relevance <= 1.0
    assert palace.relevance > monument.relevance
    assert (await session.get(Poi, "n3")).name_en == "Town Hall"
    assert city.poi_count == 17 and city.wiki_status == "done"


async def test_reingest_keeps_wikipedia_evidence(session, city):
    rows = overpass.parse_elements(SAMPLE_ELEMENTS)
    await ingest.ingest_rows(session, rows, CENTRE[0], CENTRE[1], 6000.0, "overpass")
    session.expire_all()
    palace = await session.get(Poi, "w18")
    assert palace.sitelinks == 55 and palace.wiki_known  # not wiped by a refresh without signals


async def test_ensure_area_downloads_once(session, external):
    first = await ingest.ensure_area(session, *CENTRE, 3000.0)
    second = await ingest.ensure_area(session, CENTRE[0] + 0.001, CENTRE[1], 2000.0)
    assert first.id == second.id and first.source == "overpass" and first.wiki_status == "pending"
    assert external["overpass"].call_count == 1
    assert await session.scalar(select(func.count()).select_from(Area)) == 1


async def test_ensure_area_fails_cleanly_when_all_mirrors_down(session, external):
    external["overpass"].mock(return_value=httpx.Response(502))
    with pytest.raises(ProviderError):
        await ingest.ensure_area(session, *CENTRE, 3000.0)
    assert await session.scalar(select(func.count()).select_from(Area)) == 0


async def test_stale_area_is_served_when_provider_is_down(session, external, monkeypatch):
    area = await ingest.ensure_area(session, *CENTRE, 3000.0)
    from datetime import UTC, datetime, timedelta

    area.fetched_at = datetime.now(UTC) - timedelta(days=90)
    await session.commit()
    external["overpass"].mock(side_effect=httpx.ConnectError("down"))
    again = await ingest.ensure_area(session, *CENTRE, 3000.0)
    assert again.id == area.id


async def test_enrichment_upgrades_model_inputs(session, external, engine, monkeypatch):
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from planner.service import db

    area_id = (await ingest.ensure_area(session, *CENTRE, 3000.0)).id
    external["wikidata"].mock(
        return_value=httpx.Response(
            200,
            json={
                "entities": {
                    "Q18": {"sitelinks": {"ukwiki": {}, "enwiki": {}, "dewiki": {}, "commonswiki": {}}},
                    "Q1": {"sitelinks": {"ukwiki": {}}},
                }
            },
        )  # fmt: skip
    )
    monkeypatch.setattr(db, "_factory", async_sessionmaker(engine, expire_on_commit=False))
    monkeypatch.setattr(db, "_engine", engine)
    monkeypatch.setattr(ingest.asyncio, "sleep", lambda *_: _noop())
    await ingest.enrich_area(area_id)
    session.expire_all()
    assert (await session.get(Poi, "w18")).sitelinks == 3
    assert (await session.get(Area, area_id)).wiki_status == "done"
    assert await session.scalar(select(func.count()).select_from(Poi).where(Poi.wiki_known.is_(False))) == 0


async def _noop():
    return None


async def test_overlapping_area_is_served_as_partial_and_failures_are_not_hammered(session, city, external):
    """A request reaching beyond the imported region must not hang or fail when Overpass is down."""
    external["overpass"].mock(side_effect=httpx.ConnectError("down"))
    lat, lon = CENTRE[0] + 0.04, CENTRE[1]  # ~4.4 km north: a 4 km circle sticks out of the 6 km region
    area = await ingest.ensure_area(session, lat, lon, 4000.0)
    assert area.id == city.id and area.partial is True
    again = await ingest.ensure_area(session, lat, lon, 4000.0)
    assert again.id == city.id
    assert external["overpass"].call_count == 1  # second request fails fast, no new download attempt
    with pytest.raises(ProviderError):  # a place nothing is known about still reports the outage
        await ingest.ensure_area(session, 10.0, 10.0, 3000.0)
