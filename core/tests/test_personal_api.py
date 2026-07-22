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
