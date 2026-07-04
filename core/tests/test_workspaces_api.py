from httpx import AsyncClient

SIGNUP_URL = "/api/auth/signup"
INVITES_URL = "/api/invites"
WORKSPACES_URL = "/api/workspaces"


def _signup_payload(**overrides: object) -> dict:
    payload: dict[str, object] = {
        "email": "ada@example.com",
        "password": "correct horse battery",
        "display_name": "Ada Lovelace",
    }
    payload.update(overrides)
    return payload


def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _signup(client: AsyncClient, **overrides: object) -> str:
    response = await client.post(SIGNUP_URL, json=_signup_payload(**overrides))
    return response.json()["access_token"]


async def _signup_second_user(client: AsyncClient, inviter_token: str, **overrides: object) -> str:
    invite = await client.post(INVITES_URL, headers=_auth_header(inviter_token))
    payload = _signup_payload(email="grace@example.com", display_name="Grace Hopper", **overrides)
    payload["invite_code"] = invite.json()["code"]
    response = await client.post(SIGNUP_URL, json=payload)
    return response.json()["access_token"]


async def test_create_workspace_requires_auth(client: AsyncClient) -> None:
    response = await client.post(WORKSPACES_URL, json={"name": "Home"})

    assert response.status_code == 401


async def test_create_workspace_returns_201_with_owner_role(client: AsyncClient) -> None:
    token = await _signup(client)

    response = await client.post(
        WORKSPACES_URL, headers=_auth_header(token), json={"name": "Home"}
    )

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Home"
    assert body["role"] == "owner"
    assert "id" in body


async def test_list_workspaces_returns_only_mine(client: AsyncClient) -> None:
    token_a = await _signup(client)
    token_b = await _signup_second_user(client, token_a)

    await client.post(WORKSPACES_URL, headers=_auth_header(token_a), json={"name": "Home"})
    await client.post(WORKSPACES_URL, headers=_auth_header(token_b), json={"name": "Work"})

    response = await client.get(WORKSPACES_URL, headers=_auth_header(token_a))

    names = [w["name"] for w in response.json()]
    assert names == ["Home"]


async def test_create_workspace_blank_name_returns_422(client: AsyncClient) -> None:
    token = await _signup(client)

    response = await client.post(WORKSPACES_URL, headers=_auth_header(token), json={"name": "   "})

    assert response.status_code == 422


async def test_create_calendar_requires_auth(client: AsyncClient) -> None:
    token = await _signup(client)
    workspace = await client.post(
        WORKSPACES_URL, headers=_auth_header(token), json={"name": "Home"}
    )
    workspace_id = workspace.json()["id"]

    response = await client.post(
        f"{WORKSPACES_URL}/{workspace_id}/calendars", json={"name": "Personal"}
    )

    assert response.status_code == 401


async def test_create_calendar_in_own_workspace_returns_201(client: AsyncClient) -> None:
    token = await _signup(client)
    workspace = await client.post(
        WORKSPACES_URL, headers=_auth_header(token), json={"name": "Home"}
    )
    workspace_id = workspace.json()["id"]

    response = await client.post(
        f"{WORKSPACES_URL}/{workspace_id}/calendars",
        headers=_auth_header(token),
        json={"name": "Personal"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Personal"
    assert body["workspace_id"] == workspace_id
    assert body["color"].startswith("#")


async def test_create_calendar_with_custom_color(client: AsyncClient) -> None:
    token = await _signup(client)
    workspace = await client.post(
        WORKSPACES_URL, headers=_auth_header(token), json={"name": "Home"}
    )
    workspace_id = workspace.json()["id"]

    response = await client.post(
        f"{WORKSPACES_URL}/{workspace_id}/calendars",
        headers=_auth_header(token),
        json={"name": "Personal", "color": "#ff0000"},
    )

    assert response.json()["color"] == "#ff0000"


async def test_create_calendar_with_invalid_color_returns_422(client: AsyncClient) -> None:
    token = await _signup(client)
    workspace = await client.post(
        WORKSPACES_URL, headers=_auth_header(token), json={"name": "Home"}
    )
    workspace_id = workspace.json()["id"]

    response = await client.post(
        f"{WORKSPACES_URL}/{workspace_id}/calendars",
        headers=_auth_header(token),
        json={"name": "Personal", "color": "not-a-color"},
    )

    assert response.status_code == 422


async def test_create_calendar_in_others_workspace_returns_404(client: AsyncClient) -> None:
    token_a = await _signup(client)
    token_b = await _signup_second_user(client, token_a)

    workspace = await client.post(
        WORKSPACES_URL, headers=_auth_header(token_a), json={"name": "Home"}
    )
    workspace_id = workspace.json()["id"]

    response = await client.post(
        f"{WORKSPACES_URL}/{workspace_id}/calendars",
        headers=_auth_header(token_b),
        json={"name": "Snooping"},
    )

    assert response.status_code == 404


async def test_list_calendars_in_others_workspace_returns_404(client: AsyncClient) -> None:
    token_a = await _signup(client)
    token_b = await _signup_second_user(client, token_a)

    workspace = await client.post(
        WORKSPACES_URL, headers=_auth_header(token_a), json={"name": "Home"}
    )
    workspace_id = workspace.json()["id"]

    response = await client.get(
        f"{WORKSPACES_URL}/{workspace_id}/calendars", headers=_auth_header(token_b)
    )

    assert response.status_code == 404


async def test_list_calendars_returns_own_workspace_calendars(client: AsyncClient) -> None:
    token = await _signup(client)
    workspace = await client.post(
        WORKSPACES_URL, headers=_auth_header(token), json={"name": "Home"}
    )
    workspace_id = workspace.json()["id"]
    await client.post(
        f"{WORKSPACES_URL}/{workspace_id}/calendars",
        headers=_auth_header(token),
        json={"name": "Personal"},
    )
    await client.post(
        f"{WORKSPACES_URL}/{workspace_id}/calendars",
        headers=_auth_header(token),
        json={"name": "Work"},
    )

    response = await client.get(
        f"{WORKSPACES_URL}/{workspace_id}/calendars", headers=_auth_header(token)
    )

    names = [c["name"] for c in response.json()]
    assert names == ["Personal", "Work"]


async def test_create_calendar_in_nonexistent_workspace_returns_404(client: AsyncClient) -> None:
    token = await _signup(client)

    response = await client.post(
        f"{WORKSPACES_URL}/00000000-0000-0000-0000-000000000000/calendars",
        headers=_auth_header(token),
        json={"name": "Personal"},
    )

    assert response.status_code == 404
