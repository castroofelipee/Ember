from httpx import AsyncClient

SIGNUP_URL = "/api/auth/signup"
INVITES_URL = "/api/invites"
WORKSPACES_URL = "/api/workspaces"

START = "2026-07-01T09:00:00+00:00"
END = "2026-07-01T10:00:00+00:00"


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


async def _make_calendar(client: AsyncClient, token: str) -> tuple[str, str]:
    workspace = await client.post(
        WORKSPACES_URL, headers=_auth_header(token), json={"name": "Home"}
    )
    workspace_id = workspace.json()["id"]
    calendar = await client.post(
        f"{WORKSPACES_URL}/{workspace_id}/calendars",
        headers=_auth_header(token),
        json={"name": "Personal"},
    )
    return workspace_id, calendar.json()["id"]


def _event_payload(**overrides: object) -> dict:
    payload: dict[str, object] = {
        "title": "Standup",
        "start_at": START,
        "end_at": END,
    }
    payload.update(overrides)
    return payload


async def test_create_event_requires_auth(client: AsyncClient) -> None:
    token = await _signup(client)
    _, calendar_id = await _make_calendar(client, token)

    response = await client.post(
        f"/api/calendars/{calendar_id}/events", json=_event_payload()
    )

    assert response.status_code == 401


async def test_create_event_returns_201(client: AsyncClient) -> None:
    token = await _signup(client)
    _, calendar_id = await _make_calendar(client, token)

    response = await client.post(
        f"/api/calendars/{calendar_id}/events",
        headers=_auth_header(token),
        json=_event_payload(),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["title"] == "Standup"
    assert body["calendar_id"] == calendar_id
    assert body["all_day"] is False
    assert body["attendees"] == []


async def test_create_event_with_attendees_and_color(client: AsyncClient) -> None:
    token = await _signup(client)
    _, calendar_id = await _make_calendar(client, token)

    response = await client.post(
        f"/api/calendars/{calendar_id}/events",
        headers=_auth_header(token),
        json=_event_payload(
            color="#22c55e",
            attendees=["outside@example.com", "OUTSIDE@example.com", "two@example.com"],
        ),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["color"] == "#22c55e"
    # Case-insensitive dedupe keeps the first spelling.
    assert body["attendees"] == ["outside@example.com", "two@example.com"]


async def test_create_event_rejects_end_before_start(client: AsyncClient) -> None:
    token = await _signup(client)
    _, calendar_id = await _make_calendar(client, token)

    response = await client.post(
        f"/api/calendars/{calendar_id}/events",
        headers=_auth_header(token),
        json=_event_payload(start_at=END, end_at=START),
    )

    assert response.status_code == 422


async def test_create_event_rejects_blank_title(client: AsyncClient) -> None:
    token = await _signup(client)
    _, calendar_id = await _make_calendar(client, token)

    response = await client.post(
        f"/api/calendars/{calendar_id}/events",
        headers=_auth_header(token),
        json=_event_payload(title="   "),
    )

    assert response.status_code == 422


async def test_create_event_rejects_bad_attendee_email(client: AsyncClient) -> None:
    token = await _signup(client)
    _, calendar_id = await _make_calendar(client, token)

    response = await client.post(
        f"/api/calendars/{calendar_id}/events",
        headers=_auth_header(token),
        json=_event_payload(attendees=["not-an-email"]),
    )

    assert response.status_code == 422


async def test_create_event_in_others_calendar_returns_404(client: AsyncClient) -> None:
    token_a = await _signup(client)
    token_b = await _signup_second_user(client, token_a)
    _, calendar_id = await _make_calendar(client, token_a)

    response = await client.post(
        f"/api/calendars/{calendar_id}/events",
        headers=_auth_header(token_b),
        json=_event_payload(),
    )

    assert response.status_code == 404


async def test_create_event_in_nonexistent_calendar_returns_404(client: AsyncClient) -> None:
    token = await _signup(client)

    response = await client.post(
        "/api/calendars/00000000-0000-0000-0000-000000000000/events",
        headers=_auth_header(token),
        json=_event_payload(),
    )

    assert response.status_code == 404


async def test_list_events_returns_overlapping_only(client: AsyncClient) -> None:
    token = await _signup(client)
    workspace_id, calendar_id = await _make_calendar(client, token)

    await client.post(
        f"/api/calendars/{calendar_id}/events",
        headers=_auth_header(token),
        json=_event_payload(title="In window"),
    )
    await client.post(
        f"/api/calendars/{calendar_id}/events",
        headers=_auth_header(token),
        json=_event_payload(
            title="Next week",
            start_at="2026-07-08T09:00:00+00:00",
            end_at="2026-07-08T10:00:00+00:00",
        ),
    )

    response = await client.get(
        f"{WORKSPACES_URL}/{workspace_id}/events",
        headers=_auth_header(token),
        params={"start": "2026-06-28T00:00:00+00:00", "end": "2026-07-05T00:00:00+00:00"},
    )

    assert response.status_code == 200
    titles = [e["title"] for e in response.json()]
    assert titles == ["In window"]


async def test_delete_event_removes_it(client: AsyncClient) -> None:
    token = await _signup(client)
    workspace_id, calendar_id = await _make_calendar(client, token)
    created = await client.post(
        f"/api/calendars/{calendar_id}/events",
        headers=_auth_header(token),
        json=_event_payload(),
    )
    event_id = created.json()["id"]

    response = await client.delete(f"/api/events/{event_id}", headers=_auth_header(token))
    assert response.status_code == 204

    listed = await client.get(
        f"{WORKSPACES_URL}/{workspace_id}/events",
        headers=_auth_header(token),
        params={"start": "2026-06-28T00:00:00+00:00", "end": "2026-07-05T00:00:00+00:00"},
    )
    assert listed.json() == []


async def test_delete_event_requires_auth(client: AsyncClient) -> None:
    token = await _signup(client)
    _, calendar_id = await _make_calendar(client, token)
    created = await client.post(
        f"/api/calendars/{calendar_id}/events",
        headers=_auth_header(token),
        json=_event_payload(),
    )
    event_id = created.json()["id"]

    response = await client.delete(f"/api/events/{event_id}")
    assert response.status_code == 401


async def test_delete_event_in_others_workspace_returns_404(client: AsyncClient) -> None:
    token_a = await _signup(client)
    token_b = await _signup_second_user(client, token_a)
    _, calendar_id = await _make_calendar(client, token_a)
    created = await client.post(
        f"/api/calendars/{calendar_id}/events",
        headers=_auth_header(token_a),
        json=_event_payload(),
    )
    event_id = created.json()["id"]

    response = await client.delete(f"/api/events/{event_id}", headers=_auth_header(token_b))
    assert response.status_code == 404


async def test_delete_nonexistent_event_returns_404(client: AsyncClient) -> None:
    token = await _signup(client)

    response = await client.delete(
        "/api/events/00000000-0000-0000-0000-000000000000", headers=_auth_header(token)
    )
    assert response.status_code == 404


async def test_list_events_in_others_workspace_returns_404(client: AsyncClient) -> None:
    token_a = await _signup(client)
    token_b = await _signup_second_user(client, token_a)
    workspace_id, _ = await _make_calendar(client, token_a)

    response = await client.get(
        f"{WORKSPACES_URL}/{workspace_id}/events",
        headers=_auth_header(token_b),
        params={"start": START, "end": END},
    )

    assert response.status_code == 404
