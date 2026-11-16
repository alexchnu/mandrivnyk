"""Shared fixtures. Service tests run against a real PostGIS database (``planner_test``)."""

from __future__ import annotations

import json
import os

TEST_DB = "planner_test"
_BASE_URL = os.environ.get(
    "PLANNER_TEST_DATABASE_URL", "postgresql+asyncpg://planner:planner@localhost:5544/"
)
os.environ["PLANNER_DATABASE_URL"] = _BASE_URL + TEST_DB
os.environ["PLANNER_SECRET_KEY"] = "test-secret-key-with-enough-length-0123456789"
os.environ["PLANNER_OVERPASS_URLS"] = '["https://overpass.test/api/interpreter"]'
os.environ["PLANNER_OSRM_URL"] = "https://osrm.test"
os.environ["PLANNER_PHOTON_URL"] = "https://photon.test"

import httpx  # noqa: E402
import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
import respx  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

CENTRE = (48.2921, 25.9358)  # Chernivtsi


def make_row(osm_id: int, name: str, dlat: float, dlon: float, **tags: str) -> dict:
    """A raw OSM element in Overpass JSON form, offset from the test city centre."""
    return {
        "type": "node", "id": osm_id, "lat": CENTRE[0] + dlat, "lon": CENTRE[1] + dlon,
        "tags": {"name": name, **{k.replace("__", ":"): v for k, v in tags.items()}},
    }  # fmt: skip


SAMPLE_ELEMENTS = [
    make_row(1, "Університет", 0.004, -0.010, tourism="attraction", wikidata="Q1", wikipedia="uk:Університет",
             website="https://example.org", opening_hours="Mo-Su 10:00-17:00"),
    make_row(2, "Художній музей", 0.001, 0.001, tourism="museum", wikidata="Q2", opening_hours="Tu-Su 10:00-18:00; Mo off"),
    make_row(3, "Ратуша", 0.000, 0.000, amenity="townhall", wikidata="Q3", name__en="Town Hall"),
    make_row(4, "Парк Шевченка", -0.005, 0.004, leisure="park", wikidata="Q4"),
    make_row(5, "Собор Святого Духа", 0.002, 0.003, amenity="place_of_worship", wikidata="Q5"),
    make_row(6, "Театр", 0.0015, -0.002, amenity="theatre", wikidata="Q6", website="https://theatre.example"),
    make_row(7, "Пам'ятник Шевченку", 0.0012, 0.0008, historic="monument"),
    make_row(8, "Кав'ярня «Віденська»", 0.0005, 0.0006, amenity="cafe", opening_hours="Mo-Su 08:00-22:00"),
    make_row(9, "Паб «Пінта»", -0.0004, 0.0012, amenity="pub", opening_hours="Mo-Su 16:00-02:00"),
    make_row(10, "Ринок", 0.006, 0.006, amenity="marketplace"),
    make_row(11, "Краєзнавчий музей", -0.001, -0.001, tourism="museum", opening_hours="Mo-Fr 09:00-17:00"),
    make_row(12, "Турецька криниця", 0.0025, 0.0045, historic="memorial", wikidata="Q12"),
    make_row(13, "Ресторан «Чернівці»", 0.0007, -0.0004, amenity="restaurant", website="https://rest.example"),
    make_row(14, "Вірменська церква", 0.003, 0.006, amenity="place_of_worship", wikidata="Q14", wikipedia="uk:Вірменська церква"),
    make_row(15, "Кінотеатр", -0.002, 0.002, amenity="cinema"),
    make_row(16, "Сквер", 0.0002, -0.0015, leisure="garden"),
    make_row(17, "Без категорії", 0.001, 0.001, office="company"),
    {"type": "way", "id": 18, "center": {"lat": CENTRE[0] + 0.0031, "lon": CENTRE[1] - 0.0061},
     "tags": {"name": "Резиденція митрополитів", "historic": "palace", "wikidata": "Q18", "heritage": "1"}},
]  # fmt: skip


@pytest_asyncio.fixture(scope="session")
async def engine():
    admin = create_async_engine(_BASE_URL + "postgres", isolation_level="AUTOCOMMIT")
    async with admin.connect() as conn:
        exists = await conn.scalar(text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": TEST_DB})
        if not exists:
            await conn.execute(text(f'CREATE DATABASE "{TEST_DB}"'))
    await admin.dispose()

    from planner.service import models  # noqa: F401
    from planner.service.db import Base

    engine = create_async_engine(os.environ["PLANNER_DATABASE_URL"])
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def session(engine):
    tables = "area, poi, app_user, trip, trip_stop, feedback, walk_leg, http_cache"
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    """No background jobs and no rate-limit carry-over between tests."""
    from planner.service import ingest
    from planner.service.api import auth, discovery

    monkeypatch.setattr(ingest, "schedule_enrichment", lambda area_id: None)
    auth.limiter.reset()
    discovery._search_limiter.reset()


@pytest_asyncio.fixture
async def api(engine, session):
    from planner.service.db import get_session
    from planner.service.main import app

    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def override():
        async with factory() as s:
            yield s

    app.dependency_overrides[get_session] = override
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture
def external():
    """Mocked open-data services; unmatched outbound calls fail the test."""
    with respx.mock(assert_all_called=False) as router:
        router.post("https://overpass.test/api/interpreter", name="overpass").mock(
            return_value=httpx.Response(200, json={"elements": SAMPLE_ELEMENTS})
        )
        router.get(url__startswith="https://www.wikidata.org/", name="wikidata").mock(
            return_value=httpx.Response(200, json={"entities": {}})
        )
        router.get(url__regex=r"https://\w+\.wikipedia\.org/.*", name="wikipedia").mock(
            return_value=httpx.Response(200, json={"query": {"pages": []}})
        )

        def osrm_table(request: httpx.Request) -> httpx.Response:
            coords = request.url.path.rsplit("/", 1)[1].split(";")
            pts = [tuple(map(float, c.split(","))) for c in coords]
            from planner.geo import distance_matrix_m

            dist = distance_matrix_m([p[1] for p in pts], [p[0] for p in pts]) * 1.25
            return httpx.Response(
                200, json={"code": "Ok", "durations": (dist / 1.3).tolist(), "distances": dist.tolist()}
            )

        def osrm_route(request: httpx.Request) -> httpx.Response:
            coords = [list(map(float, c.split(","))) for c in request.url.path.rsplit("/", 1)[1].split(";")]
            legs = [{"duration": 60.0, "distance": 80.0} for _ in coords[1:]]
            body = {"code": "Ok", "routes": [{"geometry": {"coordinates": coords}, "legs": legs,
                                               "duration": 60.0 * len(legs), "distance": 80.0 * len(legs)}]}  # fmt: skip
            return httpx.Response(200, json=body)

        router.get(url__startswith="https://osrm.test/table/", name="osrm_table").mock(side_effect=osrm_table)
        router.get(url__startswith="https://osrm.test/route/", name="osrm_route").mock(side_effect=osrm_route)
        router.get(url__startswith="https://photon.test/api", name="photon").mock(
            return_value=httpx.Response(200, json={"features": []})
        )
        yield router


@pytest_asyncio.fixture
async def city(session, external):
    """A small city loaded through the regular ingestion path."""
    from planner.service import ingest
    from planner.service.providers.overpass import parse_elements

    rows = parse_elements(json.loads(json.dumps(SAMPLE_ELEMENTS)))
    return await ingest.ingest_rows(session, rows, CENTRE[0], CENTRE[1], 6000.0, "import", sitelinks={
        "Q1": 40, "Q2": 6, "Q3": 12, "Q4": 3, "Q5": 8, "Q6": 9, "Q12": 2, "Q14": 5, "Q18": 55})  # fmt: skip
