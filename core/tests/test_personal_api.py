from httpx import AsyncClient


async def _signup(client: AsyncClient) -> str:
    response = await client.post(
        "/api/auth/signup",
        json={
            "email": "personal@example.com",
            "password": "correct horse battery",
            "display_name": "Personal User",
        },
    )
    return response.json()["access_token"]


async def test_update_vision_image_position_is_persisted(client: AsyncClient) -> None:
    token = await _signup(client)
    headers = {"Authorization": f"Bearer {token}"}
    created = await client.post(
        "/api/personal/items",
        headers=headers,
        json={
            "kind": "vision",
            "title": "Inspiration",
            "data": {"type": "image", "image_url": "https://example.com/image.jpg"},
        },
    )
    item = created.json()

    updated = await client.patch(
        f"/api/personal/items/{item['id']}",
        headers=headers,
        json={"data": {**item["data"], "x": 321.5, "y": 147.25}},
    )

    assert updated.status_code == 200
    assert updated.json()["data"]["x"] == 321.5
    assert updated.json()["data"]["y"] == 147.25

    listed = await client.get("/api/personal/items", headers=headers)
    persisted = next(candidate for candidate in listed.json() if candidate["id"] == item["id"])
    assert persisted["data"]["x"] == 321.5
    assert persisted["data"]["y"] == 147.25


async def test_create_finished_reading(client: AsyncClient) -> None:
    token = await _signup(client)
    response = await client.post(
        "/api/personal/readings",
        headers={"Authorization": f"Bearer {token}"},
        data={
            "title": "The Left Hand of Darkness",
            "author": "Ursula K. Le Guin",
            "genre": "Science Fiction",
            "started_at": "2026-01-10",
            "finished_at": "2026-02-02",
            "pages_read": "304",
            "total_pages": "304",
            "rating": "5",
        },
    )

    assert response.status_code == 201
    reading = response.json()
    assert reading["kind"] == "reading"
    assert reading["data"]["status"] == "finished"
    assert reading["data"]["rating"] == 5
    assert reading["data"]["finished_at"] == "2026-02-02"


async def test_create_want_to_read_without_dates_or_pages(client: AsyncClient) -> None:
    token = await _signup(client)
    response = await client.post(
        "/api/personal/readings",
        headers={"Authorization": f"Bearer {token}"},
        data={
            "title": "Parable of the Sower",
            "author": "Octavia E. Butler",
            "genre": "Science Fiction",
            "shelf": "want_to_read",
        },
    )

    assert response.status_code == 201
    reading = response.json()
    assert reading["data"]["status"] == "want_to_read"
    assert reading["data"]["started_at"] is None
    assert reading["data"]["total_pages"] == 0


async def test_update_reading_rates_and_reshelves_a_book_in_progress(client: AsyncClient) -> None:
    token = await _signup(client)
    headers = {"Authorization": f"Bearer {token}"}
    created = await client.post(
        "/api/personal/readings",
        headers=headers,
        data={
            "title": "Piranesi",
            "author": "Susanna Clarke",
            "shelf": "reading",
            "started_at": "2026-03-01",
            "pages_read": "40",
            "total_pages": "245",
        },
    )
    item = created.json()
    assert item["data"]["rating"] == 0

    updated = await client.patch(
        f"/api/personal/readings/{item['id']}",
        headers=headers,
        data={
            "title": "Piranesi",
            "author": "Susanna Clarke",
            "genre": "Fantasy",
            "shelf": "reading",
            "started_at": "2026-03-01",
            "pages_read": "120",
            "total_pages": "245",
            "rating": "4",
        },
    )

    assert updated.status_code == 200
    data = updated.json()["data"]
    assert data["rating"] == 4
    assert data["genre"] == "Fantasy"
    assert data["pages_read"] == 120
    assert data["status"] == "reading"


async def test_update_reading_to_finished_sets_finish_date(client: AsyncClient) -> None:
    token = await _signup(client)
    headers = {"Authorization": f"Bearer {token}"}
    created = await client.post(
        "/api/personal/readings",
        headers=headers,
        data={
            "title": "Dune",
            "author": "Frank Herbert",
            "shelf": "reading",
            "started_at": "2026-01-05",
            "pages_read": "100",
            "total_pages": "412",
        },
    )
    item = created.json()

    updated = await client.patch(
        f"/api/personal/readings/{item['id']}",
        headers=headers,
        data={
            "title": "Dune",
            "author": "Frank Herbert",
            "shelf": "finished",
            "started_at": "2026-01-05",
            "finished_at": "2026-02-20",
            "pages_read": "412",
            "total_pages": "412",
            "rating": "5",
        },
    )

    assert updated.status_code == 200
    data = updated.json()["data"]
    assert data["status"] == "finished"
    assert data["finished_at"] == "2026-02-20"
    assert data["rating"] == 5


async def test_update_reading_rejects_pages_beyond_total(client: AsyncClient) -> None:
    token = await _signup(client)
    headers = {"Authorization": f"Bearer {token}"}
    created = await client.post(
        "/api/personal/readings",
        headers=headers,
        data={
            "title": "Solaris",
            "author": "Stanisław Lem",
            "shelf": "reading",
            "pages_read": "10",
            "total_pages": "204",
        },
    )
    item = created.json()

    response = await client.patch(
        f"/api/personal/readings/{item['id']}",
        headers=headers,
        data={
            "title": "Solaris",
            "author": "Stanisław Lem",
            "shelf": "reading",
            "pages_read": "500",
            "total_pages": "204",
            "rating": "3",
        },
    )

    assert response.status_code == 422


async def test_update_reading_requires_auth(client: AsyncClient) -> None:
    token = await _signup(client)
    created = await client.post(
        "/api/personal/readings",
        headers={"Authorization": f"Bearer {token}"},
        data={"title": "Ubik", "author": "Philip K. Dick", "shelf": "want_to_read"},
    )
    item = created.json()

    response = await client.patch(
        f"/api/personal/readings/{item['id']}",
        data={"title": "Ubik", "author": "Philip K. Dick", "shelf": "want_to_read"},
    )

    assert response.status_code == 401


async def test_update_reading_rejects_other_kinds(client: AsyncClient) -> None:
    token = await _signup(client)
    headers = {"Authorization": f"Bearer {token}"}
    habit = await client.post(
        "/api/personal/items",
        headers=headers,
        json={"kind": "habit", "title": "Read 20 pages", "data": {}},
    )

    response = await client.patch(
        f"/api/personal/readings/{habit.json()['id']}",
        headers=headers,
        data={"title": "Read 20 pages", "author": "Me", "shelf": "reading"},
    )

    assert response.status_code == 404
