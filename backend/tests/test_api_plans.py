import httpx

from .conftest import CENTRE

SIGHTS = ["n4", "w18", "n10", "n3", "n1"]  # deliberately zig-zag order across the city


def stops(ids, **extra):
    return [{"poi_id": i, **extra} for i in ids]


async def test_optimize_shortens_walk_and_keeps_all_stops(api, city):
    base = {"stops": stops(SIGHTS), "start_date": "2026-11-18", "day_start": "09:00", "day_end": "20:00"}
    kept = (await api.post("/api/v1/plans", json={**base, "mode": "keep_order"})).json()
    best = (await api.post("/api/v1/plans", json={**base, "mode": "optimize"})).json()
    assert [v["poi"]["id"] for v in kept["days"][0]["visits"]] == SIGHTS
    assert sorted(v["poi"]["id"] for v in best["days"][0]["visits"]) == sorted(SIGHTS)
    assert best["total_walk_minutes"] < kept["total_walk_minutes"]
    assert best["saved_walk_minutes"] == round(kept["total_walk_minutes"] - best["total_walk_minutes"], 1)
    assert best["routed"] and len(best["days"][0]["geometry"]) == len(SIGHTS)
    assert best["unscheduled"] == []


async def test_timetable_is_consistent(api, city):
    plan = (
        await api.post("/api/v1/plans", json={"stops": stops(["n3", "n2", "n8"]), "start_date": "2026-11-18"})
    ).json()
    visits = plan["days"][0]["visits"]
    assert visits[0]["arrive"] == 540 and visits[0]["walk_minutes"] == 0
    for prev, cur in zip(visits[:-1], visits[1:], strict=True):
        assert cur["arrive"] == prev["leave"] + round(cur["walk_minutes"])
        assert cur["start"] >= cur["arrive"] and cur["leave"] - cur["start"] == cur["poi"]["visit_minutes"]


async def test_start_point_adds_first_leg(api, city):
    hotel = {"lat": CENTRE[0] - 0.01, "lon": CENTRE[1] - 0.01}
    plan = (
        await api.post(
            "/api/v1/plans", json={"stops": stops(["n3", "n2"]), "start": hotel, "start_date": "2026-11-18"}
        )
    ).json()
    first = plan["days"][0]["visits"][0]
    assert first["walk_minutes"] > 5 and first["arrive"] > 540
    assert len(plan["days"][0]["geometry"]) == 3


async def test_keep_order_reports_closed_and_late(api, city):
    # 2026-11-16 is a Monday: the art museum (n2) is closed, the local museum (n11) closes at 17:00
    req = {
        "stops": stops(["n2", "n1", "n11"], visit_minutes=200),
        "start_date": "2026-11-16",
        "mode": "keep_order",
    }
    plan = (await api.post("/api/v1/plans", json=req)).json()
    codes = {(w["code"], w["poi_id"]) for w in plan["warnings"]}
    assert ("closed", "n2") in codes and ("late", "n11") in codes
    assert [v["poi"]["id"] for v in plan["days"][0]["visits"]] == ["n2", "n1", "n11"]  # order untouched


async def test_optimize_moves_stop_to_a_day_when_it_is_open(api, city):
    req = {"stops": stops(["n2", "n3", "n4"]), "start_date": "2026-11-16", "days": 2}
    plan = (await api.post("/api/v1/plans", json=req)).json()
    day_of = {v["poi"]["id"]: d["index"] for d in plan["days"] for v in d["visits"]}
    assert day_of["n2"] == 1 and plan["unscheduled"] == []  # Tuesday, the museum is open again
    assert plan["days"][1]["date"] == "2026-11-17"
    assert not [w for w in plan["warnings"] if w["code"] in ("closed", "late")]


async def test_unschedulable_stop_is_reported(api, city):
    req = {"stops": stops(["n2", "n3"]), "start_date": "2026-11-16", "days": 1}
    plan = (await api.post("/api/v1/plans", json=req)).json()
    assert plan["unscheduled"] == ["n2"]
    assert {"code": "unscheduled", "poi_id": "n2", "day": None, "minutes": None} in plan["warnings"]


async def test_waiting_for_opening_is_flagged(api, city):
    req = {"stops": stops(["n1"]), "start_date": "2026-11-18", "day_start": "08:00"}
    plan = (await api.post("/api/v1/plans", json=req)).json()
    visit = plan["days"][0]["visits"][0]
    assert visit["arrive"] == 480 and visit["start"] == 600
    assert {"code": "waits", "poi_id": "n1", "day": 0, "minutes": 120} in plan["warnings"]


async def test_multi_day_respects_daily_budget(api, city):
    everything = ["w18", "n1", "n2", "n3", "n4", "n5", "n6", "n7", "n10", "n11", "n12", "n14", "n15", "n16"]
    req = {
        "stops": stops(everything),
        "start_date": "2026-11-18",
        "days": 3,
        "day_start": "10:00",
        "day_end": "15:00",
    }
    plan = (await api.post("/api/v1/plans", json=req)).json()
    visited = [v["poi"]["id"] for d in plan["days"] for v in d["visits"]]
    assert len(visited) == len(set(visited)) and set(visited) | set(plan["unscheduled"]) == set(everything)
    assert len(visited) >= 10
    for day in plan["days"]:
        assert all(v["start"] >= 600 and v["leave"] <= 900 for v in day["visits"])


async def test_optional_places_fill_free_time(api, city):
    req = {"stops": stops(["n3"]), "optional_ids": ["w18", "n2", "n3"], "start_date": "2026-11-18"}
    plan = (await api.post("/api/v1/plans", json=req)).json()
    visits = {v["poi"]["id"]: v["optional"] for v in plan["days"][0]["visits"]}
    assert visits == {"n3": False, "w18": True, "n2": True}
    assert {w["poi_id"] for w in plan["warnings"] if w["code"] == "added"} == {"w18", "n2"}


async def test_routing_outage_falls_back_to_estimates(api, city, external):
    external["osrm_table"].mock(side_effect=httpx.ConnectError("down"))
    plan = (await api.post("/api/v1/plans", json={"stops": stops(SIGHTS)})).json()
    assert plan["routed"] is False and plan["total_walk_minutes"] > 0
    assert {"code": "estimated_walk", "poi_id": None, "day": None, "minutes": None} in plan["warnings"]
    assert sorted(v["poi"]["id"] for v in plan["days"][0]["visits"]) == sorted(SIGHTS)


async def test_walking_times_are_cached(api, city, external):
    await api.post("/api/v1/plans", json={"stops": stops(SIGHTS)})
    await api.post("/api/v1/plans", json={"stops": stops(SIGHTS[:3]), "mode": "keep_order"})
    assert external["osrm_table"].call_count == 1  # the subset is answered from the leg cache


async def test_plan_validation(api, city):
    assert (await api.post("/api/v1/plans", json={"stops": stops(["n3", "n424242"])})).status_code == 404
    assert (await api.post("/api/v1/plans", json={"stops": stops(["n3", "n3"])})).status_code == 422
    assert (await api.post("/api/v1/plans", json={"stops": []})).status_code == 422
    bad_day = {"stops": stops(["n3"]), "day_start": "18:00", "day_end": "18:30"}
    assert (await api.post("/api/v1/plans", json=bad_day)).status_code == 422
