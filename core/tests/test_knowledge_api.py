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


async def _signup_second_user(client: AsyncClient, inviter_token: str) -> str:
    invite = await client.post(INVITES_URL, headers=_auth_header(inviter_token))
    payload = _signup_payload(email="grace@example.com", display_name="Grace Hopper")
    payload["invite_code"] = invite.json()["code"]
    response = await client.post(SIGNUP_URL, json=payload)
    return response.json()["access_token"]


async def _make_workspace(client: AsyncClient, token: str) -> str:
    response = await client.post(
        WORKSPACES_URL, headers=_auth_header(token), json={"name": "Home"}
    )
    return response.json()["id"]


async def _make_board(client: AsyncClient, token: str, workspace_id: str) -> dict:
    response = await client.post(
        f"{WORKSPACES_URL}/{workspace_id}/boards",
        headers=_auth_header(token),
        json={"title": "Product", "initial_columns": ["Backlog", "Doing", "Done"]},
    )
    return response.json()


async def test_move_board_column_reorders_columns(client: AsyncClient) -> None:
    token = await _signup(client)
    workspace_id = await _make_workspace(client, token)
    board = await _make_board(client, token, workspace_id)
    board_id = board["id"]
    backlog = board["columns"][0]

    response = await client.patch(
        f"{WORKSPACES_URL}/{workspace_id}/boards/{board_id}/columns/{backlog['id']}",
        headers=_auth_header(token),
        json={"position": 2},
    )

    assert response.status_code == 200
    columns = response.json()["columns"]
    assert [column["title"] for column in columns] == ["Doing", "Done", "Backlog"]
    assert [column["position"] for column in columns] == [0, 1, 2]


async def test_move_board_column_in_others_workspace_returns_404(client: AsyncClient) -> None:
    token_a = await _signup(client)
    token_b = await _signup_second_user(client, token_a)
    workspace_id = await _make_workspace(client, token_a)
    board = await _make_board(client, token_a, workspace_id)
    column = board["columns"][0]

    response = await client.patch(
        f"{WORKSPACES_URL}/{workspace_id}/boards/{board['id']}/columns/{column['id']}",
        headers=_auth_header(token_b),
        json={"position": 2},
    )

    assert response.status_code == 404
