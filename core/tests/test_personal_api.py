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
