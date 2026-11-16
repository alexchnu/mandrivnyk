import httpx

from .conftest import CENTRE

REQ = {"lat": CENTRE[0], "lon": CENTRE[1], "radius_km": 3, "limit": 8}


async def test_health_and_categories(api):
    assert (await api.get("/api/v1/health")).json()["status"] == "ok"
    cats = (await api.get("/api/v1/categories")).json()
    assert [c["id"] for c in cats][:2] == ["culture", "history"] and "museum" in cats[0]["subtypes"]


async def test_recommendations_are_diverse_and_explained(api, city):
    body = (await api.post("/api/v1/recommendations", json=REQ)).json()
    items = body["items"]
    assert len(items) == 8 and body["total_candidates"] == 17 and body["data_status"] == "fresh"
    assert len({i["id"] for i in items}) == 8
    assert len({i["category"] for i in items}) >= 5  # diversified page
    assert items[0]["id"] in {"w18", "n1", "n3"}  # the most notable places lead the list
    assert all(i["distance_m"] <= 3000 for i in items)
    assert any(r["code"] == "wiki_languages" for r in items[0]["reasons"])


async def test_first_request_downloads_city(api, session, external):
    resp = await api.post("/api/v1/recommendations", json=REQ)
    assert resp.status_code == 200 and resp.json()["enrichment"] == "pending"
    assert external["overpass"].call_count == 1
    await api.post("/api/v1/recommendations", json=REQ)
    assert external["overpass"].call_count == 1  # second request is served from the database


async def test_provider_outage_is_a_503(api, session, external):
    external["overpass"].mock(side_effect=httpx.ConnectTimeout("down"))
    resp = await api.post("/api/v1/recommendations", json=REQ)
    assert resp.status_code == 503 and "unavailable" in resp.json()["detail"]


async def test_paging_never_repeats(api, city):
    seen: list[str] = []
    for _ in range(3):
        items = (
            await api.post("/api/v1/recommendations", json={**REQ, "limit": 6, "exclude_ids": seen})
        ).json()["items"]
        assert not set(seen) & {i["id"] for i in items}
        seen += [i["id"] for i in items]
    assert len(seen) == 17  # 6 + 6 + 5: every candidate shown exactly once


async def test_filters_and_preferences(api, city):
    only = (await api.post("/api/v1/recommendations", json={**REQ, "categories": ["culture"]})).json()[
        "items"
    ]
    assert {i["category"] for i in only} == {"culture"} and len(only) == 2
    liked = (
        await api.post("/api/v1/recommendations", json={**REQ, "limit": 3, "preferences": {"food": 2}})
    ).json()["items"]
    plain = (await api.post("/api/v1/recommendations", json={**REQ, "limit": 3})).json()["items"]
    assert "food" in {i["category"] for i in liked} and "food" not in {i["category"] for i in plain}
    disliked = (
        await api.post("/api/v1/recommendations", json={**REQ, "limit": 17, "preferences": {"history": -1}})
    ).json()["items"]
    ranks = [k for k, i in enumerate(disliked) if i["category"] == "history"]
    base = (await api.post("/api/v1/recommendations", json={**REQ, "limit": 17})).json()["items"]
    assert min(ranks) > min(k for k, i in enumerate(base) if i["category"] == "history")


async def test_context_of_selected_stops(api, city):
    resp = await api.post("/api/v1/recommendations", json={
        **REQ, "selected_ids": ["w18", "n1"], "anchor": {"lat": CENTRE[0] + 0.0031, "lon": CENTRE[1] - 0.0061}})  # fmt: skip
    items = resp.json()["items"]
    assert "w18" not in {i["id"] for i in items} and "n1" not in {i["id"] for i in items}
    assert any(r["code"] == "new_category" for i in items for r in i["reasons"])
    # closeness is measured from the anchor (the last stop), not from the city centre
    near = min(items, key=lambda i: i["distance_m"])
    assert near["distance_m"] < 1200


async def test_methods_differ_only_in_composition(api, city):
    lists = {}
    for method in ("top_k", "round_robin", "mmr", "xquad"):
        items = (
            await api.post("/api/v1/recommendations", json={**REQ, "limit": 6, "method": method})
        ).json()["items"]
        lists[method] = items
        assert len(items) == 6
    cats = {m: len({i["category"] for i in items}) for m, items in lists.items()}
    assert cats["round_robin"] >= cats["top_k"] and cats["xquad"] >= cats["top_k"]


async def test_validation(api, city):
    for bad in (
        {"radius_km": 50},
        {"lat": 100},
        {"categories": ["casino"]},
        {"limit": 0},
        {"exclude_ids": ["x1"]},
    ):
        assert (await api.post("/api/v1/recommendations", json={**REQ, **bad})).status_code == 422


async def test_summaries_are_fetched_once_and_cached(api, city, external):
    external["wikidata"].mock(return_value=httpx.Response(200, json={
        "entities": {"Q18": {"sitelinks": {"ukwiki": {"title": "Резиденція"}}}}}))  # fmt: skip
    wiki = external["wikipedia"].mock(return_value=httpx.Response(200, json={
        "query": {"pages": [
            {"title": "Резиденція", "extract": "Архітектурний ансамбль.", "thumbnail": {"source": "https://img/x.jpg"},
             "fullurl": "https://uk.wikipedia.org/wiki/X"},
            {"title": "Університет", "extract": "Заклад освіти.", "fullurl": "https://uk.wikipedia.org/wiki/U"}]}}))  # fmt: skip
    first = (await api.post("/api/v1/recommendations", json=REQ)).json()["items"]
    by_id = {i["id"]: i for i in first}
    assert (
        by_id["w18"]["summary"]["extract"] == "Архітектурний ансамбль." and by_id["w18"]["summary"]["image"]
    )
    assert by_id["n1"]["summary"]["title"] == "Університет"
    assert all(i["summary"] is None for i in first if i["id"] not in ("w18", "n1"))  # no article, no summary
    calls = wiki.call_count
    again = (await api.post("/api/v1/recommendations", json=REQ)).json()["items"]
    assert wiki.call_count == calls and {i["id"]: i for i in again}["w18"]["summary"]["image"]


async def test_wikipedia_outage_does_not_break_recommendations(api, city, external):
    external["wikidata"].mock(side_effect=httpx.ConnectError("down"))
    external["wikipedia"].mock(side_effect=httpx.ConnectError("down"))
    resp = await api.post("/api/v1/recommendations", json=REQ)
    assert resp.status_code == 200 and len(resp.json()["items"]) == 8


async def test_place_search_is_cached_and_survives_outage(api, session, external):
    route = external["photon"].mock(return_value=httpx.Response(200, json={
        "features": [
            {"geometry": {"coordinates": [25.9358, 48.2921]},
             "properties": {"name": "Чернівці", "country": "Україна", "countrycode": "UA", "type": "city",
                            "state": "Чернівецька область", "extent": [25.8, 48.4, 26.1, 48.2]}},
            {"geometry": {"coordinates": [25.9358, 48.2921]},
             "properties": {"name": "Чернівці", "country": "Україна", "countrycode": "UA", "type": "city",
                            "state": "Чернівецька область"}}]}))  # fmt: skip
    first = (await api.get("/api/v1/places", params={"q": "Чернів"})).json()
    assert len(first) == 1 and first[0]["label"] == "Чернівці, Чернівецька область, Україна"
    assert first[0]["country_code"] == "ua"
    route.mock(side_effect=httpx.ConnectError("down"))
    assert (await api.get("/api/v1/places", params={"q": "чернів"})).json() == first
    assert route.call_count == 1
    assert (await api.get("/api/v1/places", params={"q": "x"})).status_code == 422
    assert (await api.get("/api/v1/places", params={"q": "Львів"})).status_code == 503


async def test_feedback_is_stored(api, session, city):
    from sqlalchemy import func, select

    from planner.service.models import Feedback

    resp = await api.post("/api/v1/feedback", headers={"X-Client-Id": "c" * 20}, json=[
        {"poi_id": "w18", "action": "added", "rank": 0}, {"poi_id": "n999", "action": "shown"}])  # fmt: skip
    assert resp.status_code == 204
    assert await session.scalar(select(func.count()).select_from(Feedback)) == 1  # unknown place ignored
    assert (await api.post("/api/v1/feedback", json=[])).status_code == 422


async def test_partial_data_is_flagged(api, city, external):
    external["overpass"].mock(side_effect=httpx.ConnectError("down"))
    body = (
        await api.post("/api/v1/recommendations", json={**REQ, "lat": CENTRE[0] + 0.04, "radius_km": 4})
    ).json()
    assert body["data_status"] == "partial" and len(body["items"]) > 0
