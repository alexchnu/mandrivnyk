from .conftest import CENTRE

ANON_A = {"X-Client-Id": "a" * 24}
ANON_B = {"X-Client-Id": "b" * 24}
TRIP = {
    "title": "Вихідні в Чернівцях", "city": "Чернівці", "lat": CENTRE[0], "lon": CENTRE[1], "n_days": 2,
    "start_date": "2026-11-21",
    "stops": [{"poi_id": "w18", "day_index": 0}, {"poi_id": "n3", "day_index": 0, "note": "кава поруч"},
              {"poi_id": "n4", "day_index": 1, "visit_minutes": 90}],
}  # fmt: skip


async def register(api, email="olena@example.com", password="correct horse", headers=None):
    resp = await api.post("/api/v1/auth/register", headers=headers or {},
                          json={"email": email, "password": password, "display_name": "Олена"})  # fmt: skip
    assert resp.status_code == 201, resp.text
    return {"Authorization": f"Bearer {resp.json()['token']}"}, resp.json()


async def test_anonymous_trip_lifecycle(api, city):
    created = await api.post("/api/v1/trips", json=TRIP, headers=ANON_A)
    assert created.status_code == 201
    trip = created.json()
    assert [(s["poi"]["id"], s["day_index"], s["position"]) for s in trip["stops"]] == [
        ("w18", 0, 0), ("n3", 0, 1), ("n4", 1, 0)]  # fmt: skip
    assert trip["stops"][1]["note"] == "кава поруч" and trip["stops"][2]["visit_minutes"] == 90

    listing = (await api.get("/api/v1/trips", headers=ANON_A)).json()
    assert [t["id"] for t in listing] == [trip["id"]] and listing[0]["stop_count"] == 3

    changed = {**TRIP, "title": "Новий план", "n_days": 1, "stops": [{"poi_id": "n4"}, {"poi_id": "w18"}]}
    updated = (await api.put(f"/api/v1/trips/{trip['id']}", json=changed, headers=ANON_A)).json()
    assert updated["title"] == "Новий план" and [s["poi"]["id"] for s in updated["stops"]] == ["n4", "w18"]

    assert (await api.delete(f"/api/v1/trips/{trip['id']}", headers=ANON_A)).status_code == 204
    assert (await api.get(f"/api/v1/trips/{trip['id']}", headers=ANON_A)).status_code == 404


async def test_trips_are_private(api, city):
    trip = (await api.post("/api/v1/trips", json=TRIP, headers=ANON_A)).json()
    url = f"/api/v1/trips/{trip['id']}"
    assert (await api.get(url, headers=ANON_B)).status_code == 404
    assert (await api.get(url)).status_code == 404
    assert (await api.put(url, json=TRIP, headers=ANON_B)).status_code == 404
    assert (await api.delete(url, headers=ANON_B)).status_code == 404
    assert (await api.post(f"{url}/share", headers=ANON_B)).status_code == 404
    assert (await api.get("/api/v1/trips", headers=ANON_B)).json() == []
    assert (await api.get("/api/v1/trips")).status_code == 400  # no identity at all
    assert (await api.get(url, headers=ANON_A)).status_code == 200


async def test_user_cannot_touch_another_users_trip(api, city):
    olena, _ = await register(api)
    taras, _ = await register(api, "taras@example.com")
    trip = (await api.post("/api/v1/trips", json=TRIP, headers=olena)).json()
    url = f"/api/v1/trips/{trip['id']}"
    assert (await api.get(url, headers=taras)).status_code == 404
    assert (await api.put(url, json=TRIP, headers=taras)).status_code == 404
    assert (await api.delete(url, headers=taras)).status_code == 404
    assert (await api.get("/api/v1/trips", headers=taras)).json() == []
    # the owner's browser id alone is not enough once the trip belongs to an account
    assert (await api.get(url, headers=ANON_A)).status_code == 404
    assert (await api.get(url, headers=olena)).status_code == 200


async def test_sharing_gives_read_only_access(api, city):
    trip = (await api.post("/api/v1/trips", json=TRIP, headers=ANON_A)).json()
    shared = (await api.post(f"/api/v1/trips/{trip['id']}/share", headers=ANON_A)).json()
    slug = shared["share_slug"]
    assert (
        slug
        and (await api.post(f"/api/v1/trips/{trip['id']}/share", headers=ANON_A)).json()["share_slug"] == slug
    )
    public = await api.get(f"/api/v1/trips/shared/{slug}", headers=ANON_B)
    assert (
        public.status_code == 200 and public.json()["editable"] is False and len(public.json()["stops"]) == 3
    )
    assert (await api.get(f"/api/v1/trips/shared/{slug}", headers=ANON_A)).json()["editable"] is True
    assert (await api.put(f"/api/v1/trips/{trip['id']}", json=TRIP, headers=ANON_B)).status_code == 404
    await api.delete(f"/api/v1/trips/{trip['id']}/share", headers=ANON_A)
    assert (await api.get(f"/api/v1/trips/shared/{slug}")).status_code == 404


async def test_trip_validation(api, city):
    assert (
        await api.post("/api/v1/trips", json={**TRIP, "stops": [{"poi_id": "n77777"}]}, headers=ANON_A)
    ).status_code == 404
    dup = {**TRIP, "stops": [{"poi_id": "n3"}, {"poi_id": "n3"}]}
    assert (await api.post("/api/v1/trips", json=dup, headers=ANON_A)).status_code == 422
    assert (await api.post("/api/v1/trips", json={**TRIP, "title": ""}, headers=ANON_A)).status_code == 422
    assert (
        await api.post(
            "/api/v1/trips", json={**TRIP, "day_start_min": 600, "day_end_min": 620}, headers=ANON_A
        )
    ).status_code == 422
    assert (await api.post("/api/v1/trips", json=TRIP, headers={"X-Client-Id": "short"})).status_code == 400
    assert (await api.get("/api/v1/trips/not-a-uuid", headers=ANON_A)).status_code == 422


async def test_register_login_me(api, session):
    headers, body = await register(api, "Olena@Example.com")
    assert body["user"]["email"] == "olena@example.com" and body["user"]["display_name"] == "Олена"
    assert (await api.get("/api/v1/auth/me", headers=headers)).json()["email"] == "olena@example.com"

    ok = await api.post(
        "/api/v1/auth/login", json={"email": "OLENA@example.com", "password": "correct horse"}
    )
    assert ok.status_code == 200 and ok.json()["user"]["id"] == body["user"]["id"]
    wrong = await api.post("/api/v1/auth/login", json={"email": "olena@example.com", "password": "nope"})
    ghost = await api.post("/api/v1/auth/login", json={"email": "ghost@example.com", "password": "nope"})
    assert (
        wrong.status_code == ghost.status_code == 401 and wrong.json() == ghost.json()
    )  # no account enumeration

    from sqlalchemy import select

    from planner.service.models import User

    stored = await session.scalar(select(User.password_hash))
    assert stored.startswith("$argon2id$") and "correct horse" not in stored


async def test_registration_rules(api, session):
    await register(api)
    again = await api.post("/api/v1/auth/register",
                           json={"email": "OLENA@example.com", "password": "another pass", "display_name": "X"})  # fmt: skip
    assert again.status_code == 409
    for bad in ({"password": "short"}, {"email": "not-an-email"}, {"display_name": "   "}):
        data = {"email": "new@example.com", "password": "long enough", "display_name": "N", **bad}
        assert (await api.post("/api/v1/auth/register", json=data)).status_code == 422


async def test_tokens_are_verified(api, session):
    headers, _ = await register(api)
    assert (await api.get("/api/v1/auth/me")).status_code == 401
    assert (await api.get("/api/v1/auth/me", headers={"Authorization": "Bearer garbage"})).status_code == 401
    tampered = headers["Authorization"][:-3] + "abc"
    assert (await api.get("/api/v1/auth/me", headers={"Authorization": tampered})).status_code == 401
    assert (
        await api.get(
            "/api/v1/auth/me", headers={"Authorization": headers["Authorization"].replace("Bearer", "Basic")}
        )
    ).status_code == 401

    import jwt

    forged = jwt.encode(
        {"sub": "00000000-0000-0000-0000-000000000000"},
        "another-secret-another-secret-0000",
        algorithm="HS256",
    )
    assert (
        await api.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {forged}"})
    ).status_code == 401


async def test_anonymous_trips_follow_the_account(api, city):
    trip = (await api.post("/api/v1/trips", json=TRIP, headers=ANON_A)).json()
    auth, body = await register(api, headers=ANON_A)
    assert body["claimed_trips"] == 1
    # visible from any device after sign-in, and no longer reachable by the bare browser id
    assert [t["id"] for t in (await api.get("/api/v1/trips", headers=auth)).json()] == [trip["id"]]
    assert (await api.get(f"/api/v1/trips/{trip['id']}", headers=ANON_A)).status_code == 404
    # trips made on another browser are claimed at login
    other = (await api.post("/api/v1/trips", json={**TRIP, "title": "Інший"}, headers=ANON_B)).json()
    login = await api.post(
        "/api/v1/auth/login", headers=ANON_B, json={"email": "olena@example.com", "password": "correct horse"}
    )
    assert login.json()["claimed_trips"] == 1
    assert {t["id"] for t in (await api.get("/api/v1/trips", headers=auth)).json()} == {
        trip["id"],
        other["id"],
    }


async def test_login_is_rate_limited(api, session):
    await register(api)
    codes = [
        (
            await api.post(
                "/api/v1/auth/login", json={"email": "olena@example.com", "password": f"guess-{i}"}
            )
        ).status_code
        for i in range(12)
    ]
    assert codes[:9] == [401] * 9 and codes[-1] == 429
