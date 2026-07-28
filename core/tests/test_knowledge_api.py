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


async def _make_card(
    client: AsyncClient, token: str, workspace_id: str, board_id: str, column_id: str, title: str
) -> dict:
    response = await client.post(
        f"{WORKSPACES_URL}/{workspace_id}/boards/{board_id}/cards/new",
        headers=_auth_header(token),
        json={"column_id": column_id, "type": "task", "title": title},
    )
    return response.json()


def _column_card_titles(board: dict, column_id: str) -> list[str]:
    cards = [card for card in board["cards"] if card["column_id"] == column_id]
    cards.sort(key=lambda card: card["position"])
    return [card["entity"]["title"] for card in cards]


async def test_move_board_card_inserts_at_position(client: AsyncClient) -> None:
    token = await _signup(client)
    workspace_id = await _make_workspace(client, token)
    board = await _make_board(client, token, workspace_id)
    board_id = board["id"]
    backlog = board["columns"][0]["id"]
    for title in ("First", "Second", "Third"):
        board = await _make_card(client, token, workspace_id, board_id, backlog, title)
    third = next(
        card for card in board["cards"] if card["entity"]["title"] == "Third"
    )["entity"]["id"]

    response = await client.patch(
        f"{WORKSPACES_URL}/{workspace_id}/boards/{board_id}/cards/{third}",
        headers=_auth_header(token),
        json={"column_id": backlog, "position": 1},
    )

    assert response.status_code == 200
    assert _column_card_titles(response.json(), backlog) == ["First", "Third", "Second"]
    positions = [card["position"] for card in response.json()["cards"]]
    assert sorted(positions) == [0, 1, 2]


async def test_move_board_card_to_other_column_compacts_source(client: AsyncClient) -> None:
    token = await _signup(client)
    workspace_id = await _make_workspace(client, token)
    board = await _make_board(client, token, workspace_id)
    board_id = board["id"]
    backlog = board["columns"][0]["id"]
    doing = board["columns"][1]["id"]
    for title in ("First", "Second", "Third"):
        board = await _make_card(client, token, workspace_id, board_id, backlog, title)
    await _make_card(client, token, workspace_id, board_id, doing, "Existing")
    first = next(
        card for card in board["cards"] if card["entity"]["title"] == "First"
    )["entity"]["id"]

    response = await client.patch(
        f"{WORKSPACES_URL}/{workspace_id}/boards/{board_id}/cards/{first}",
        headers=_auth_header(token),
        json={"column_id": doing, "position": 0},
    )

    assert response.status_code == 200
    moved = response.json()
    assert _column_card_titles(moved, doing) == ["First", "Existing"]
    assert _column_card_titles(moved, backlog) == ["Second", "Third"]
    backlog_positions = [
        card["position"] for card in moved["cards"] if card["column_id"] == backlog
    ]
    assert sorted(backlog_positions) == [0, 1]


async def test_delete_board_removes_it(client: AsyncClient) -> None:
    token = await _signup(client)
    workspace_id = await _make_workspace(client, token)
    board = await _make_board(client, token, workspace_id)

    response = await client.delete(
        f"{WORKSPACES_URL}/{workspace_id}/boards/{board['id']}",
        headers=_auth_header(token),
    )

    assert response.status_code == 204
    listed = await client.get(
        f"{WORKSPACES_URL}/{workspace_id}/boards",
        headers=_auth_header(token),
    )
    assert listed.status_code == 200
    assert listed.json() == []


async def test_delete_board_in_others_workspace_returns_404(client: AsyncClient) -> None:
    token_a = await _signup(client)
    token_b = await _signup_second_user(client, token_a)
    workspace_id = await _make_workspace(client, token_a)
    board = await _make_board(client, token_a, workspace_id)

    response = await client.delete(
        f"{WORKSPACES_URL}/{workspace_id}/boards/{board['id']}",
        headers=_auth_header(token_b),
    )

    assert response.status_code == 404


async def test_update_board_assignment_options(client: AsyncClient) -> None:
    token = await _signup(client)
    workspace_id = await _make_workspace(client, token)
    board = await _make_board(client, token, workspace_id)

    response = await client.patch(
        f"{WORKSPACES_URL}/{workspace_id}/boards/{board['id']}",
        headers=_auth_header(token),
        json={
            "label_options": ["Urgent", " Backend ", "urgent"],
            "assignee_options": ["Felipe", " Ana ", "felipe"],
        },
    )

    assert response.status_code == 200
    assert response.json()["label_options"] == ["Urgent", "Backend"]
    assert response.json()["assignee_options"] == ["Felipe", "Ana"]


async def test_set_label_colors(client: AsyncClient) -> None:
    token = await _signup(client)
    workspace_id = await _make_workspace(client, token)
    board = await _make_board(client, token, workspace_id)
    await client.patch(
        f"{WORKSPACES_URL}/{workspace_id}/boards/{board['id']}",
        headers=_auth_header(token),
        json={"label_options": ["Urgent", "Backend"]},
    )

    response = await client.patch(
        f"{WORKSPACES_URL}/{workspace_id}/boards/{board['id']}",
        headers=_auth_header(token),
        json={"label_colors": {"Urgent": "#F00", "Backend": "#7C3AED"}},
    )

    assert response.status_code == 200
    assert response.json()["label_colors"] == {"Urgent": "#ff0000", "Backend": "#7c3aed"}


async def test_removing_a_label_drops_its_color(client: AsyncClient) -> None:
    token = await _signup(client)
    workspace_id = await _make_workspace(client, token)
    board = await _make_board(client, token, workspace_id)
    await client.patch(
        f"{WORKSPACES_URL}/{workspace_id}/boards/{board['id']}",
        headers=_auth_header(token),
        json={"label_options": ["Urgent", "Backend"], "label_colors": {"Urgent": "#ff0000"}},
    )

    response = await client.patch(
        f"{WORKSPACES_URL}/{workspace_id}/boards/{board['id']}",
        headers=_auth_header(token),
        json={"label_options": ["Backend"]},
    )

    assert response.status_code == 200
    assert response.json()["label_colors"] == {}


async def test_non_hex_label_color_is_rejected(client: AsyncClient) -> None:
    token = await _signup(client)
    workspace_id = await _make_workspace(client, token)
    board = await _make_board(client, token, workspace_id)

    response = await client.patch(
        f"{WORKSPACES_URL}/{workspace_id}/boards/{board['id']}",
        headers=_auth_header(token),
        json={"label_colors": {"Urgent": "red; background: url(evil)"}},
    )

    assert response.status_code == 422


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


async def test_create_folder_inside_folder(client: AsyncClient) -> None:
    token = await _signup(client)
    workspace_id = await _make_workspace(client, token)

    parent = await client.post(
        f"{WORKSPACES_URL}/{workspace_id}/folders",
        headers=_auth_header(token),
        json={"title": "Projects", "parent_id": None},
    )
    child = await client.post(
        f"{WORKSPACES_URL}/{workspace_id}/folders",
        headers=_auth_header(token),
        json={"title": "Ember", "parent_id": parent.json()["id"]},
    )

    assert child.status_code == 201
    assert child.json()["parent_id"] == parent.json()["id"]

    listed = await client.get(
        f"{WORKSPACES_URL}/{workspace_id}/folders",
        headers=_auth_header(token),
    )
    folders = {folder["title"]: folder for folder in listed.json()}
    assert folders["Projects"]["parent_id"] is None
    assert folders["Ember"]["parent_id"] == folders["Projects"]["id"]


async def test_move_folder_inside_another_folder(client: AsyncClient) -> None:
    token = await _signup(client)
    workspace_id = await _make_workspace(client, token)
    parent = await client.post(
        f"{WORKSPACES_URL}/{workspace_id}/folders",
        headers=_auth_header(token),
        json={"title": "Projects", "parent_id": None},
    )
    child = await client.post(
        f"{WORKSPACES_URL}/{workspace_id}/folders",
        headers=_auth_header(token),
        json={"title": "Ember", "parent_id": None},
    )

    moved = await client.patch(
        f"{WORKSPACES_URL}/{workspace_id}/folders/{child.json()['id']}",
        headers=_auth_header(token),
        json={"parent_id": parent.json()["id"]},
    )

    assert moved.status_code == 200
    assert moved.json()["parent_id"] == parent.json()["id"]


async def test_move_folder_back_to_root(client: AsyncClient) -> None:
    token = await _signup(client)
    workspace_id = await _make_workspace(client, token)
    parent = await client.post(
        f"{WORKSPACES_URL}/{workspace_id}/folders",
        headers=_auth_header(token),
        json={"title": "Projects", "parent_id": None},
    )
    child = await client.post(
        f"{WORKSPACES_URL}/{workspace_id}/folders",
        headers=_auth_header(token),
        json={"title": "Ember", "parent_id": parent.json()["id"]},
    )

    moved = await client.patch(
        f"{WORKSPACES_URL}/{workspace_id}/folders/{child.json()['id']}",
        headers=_auth_header(token),
        json={"parent_id": None},
    )

    assert moved.status_code == 200
    assert moved.json()["parent_id"] is None


async def test_move_folder_inside_descendant_returns_422(client: AsyncClient) -> None:
    token = await _signup(client)
    workspace_id = await _make_workspace(client, token)
    parent = await client.post(
        f"{WORKSPACES_URL}/{workspace_id}/folders",
        headers=_auth_header(token),
        json={"title": "Projects", "parent_id": None},
    )
    child = await client.post(
        f"{WORKSPACES_URL}/{workspace_id}/folders",
        headers=_auth_header(token),
        json={"title": "Ember", "parent_id": parent.json()["id"]},
    )

    response = await client.patch(
        f"{WORKSPACES_URL}/{workspace_id}/folders/{parent.json()['id']}",
        headers=_auth_header(token),
        json={"parent_id": child.json()["id"]},
    )

    assert response.status_code == 422
