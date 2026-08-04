from datetime import datetime

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


async def test_move_event_updates_start_and_end(client: AsyncClient) -> None:
    token = await _signup(client)
    workspace_id, calendar_id = await _make_calendar(client, token)
    created = await client.post(
        f"/api/calendars/{calendar_id}/events",
        headers=_auth_header(token),
        json=_event_payload(),
    )
    event_id = created.json()["id"]

    response = await client.patch(
        f"/api/events/{event_id}",
        headers=_auth_header(token),
        json={
            "start_at": "2026-07-02T11:15:00+00:00",
            "end_at": "2026-07-02T12:15:00+00:00",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["start_at"] == "2026-07-02T11:15:00Z"
    assert body["end_at"] == "2026-07-02T12:15:00Z"

    listed = await client.get(
        f"{WORKSPACES_URL}/{workspace_id}/events",
        headers=_auth_header(token),
        params={"start": "2026-07-02T00:00:00+00:00", "end": "2026-07-03T00:00:00+00:00"},
    )
    assert [event["id"] for event in listed.json()] == [event_id]


async def test_move_recurring_event_moves_selected_occurrence_only(client: AsyncClient) -> None:
    token = await _signup(client)
    workspace_id, calendar_id = await _make_calendar(client, token)
    created = await client.post(
        f"/api/calendars/{calendar_id}/events",
        headers=_auth_header(token),
        json=_event_payload(recurrence={"freq": "DAILY", "count": 3}),
    )
    event_id = created.json()["id"]

    response = await client.patch(
        f"/api/events/{event_id}",
        headers=_auth_header(token),
        json={
            "start_at": "2026-07-04T14:30:00+00:00",
            "end_at": "2026-07-04T15:30:00+00:00",
            "occurrence_start": "2026-07-02T09:00:00+00:00",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["id"] != event_id
    assert body["recurrence"] is None
    assert body["start_at"] == "2026-07-04T14:30:00Z"
    assert body["end_at"] == "2026-07-04T15:30:00Z"

    listed = await client.get(
        f"{WORKSPACES_URL}/{workspace_id}/events",
        headers=_auth_header(token),
        params={"start": "2026-07-01T00:00:00+00:00", "end": "2026-07-05T00:00:00+00:00"},
    )
    starts = [datetime.fromisoformat(event["start_at"]) for event in listed.json()]
    assert starts == [
        datetime.fromisoformat("2026-07-01T09:00:00+00:00"),
        datetime.fromisoformat("2026-07-03T09:00:00+00:00"),
        datetime.fromisoformat("2026-07-04T14:30:00+00:00"),
    ]


async def test_move_event_rejects_end_before_start(client: AsyncClient) -> None:
    token = await _signup(client)
    _, calendar_id = await _make_calendar(client, token)
    created = await client.post(
        f"/api/calendars/{calendar_id}/events",
        headers=_auth_header(token),
        json=_event_payload(),
    )
    event_id = created.json()["id"]

    response = await client.patch(
        f"/api/events/{event_id}",
        headers=_auth_header(token),
        json={"start_at": END, "end_at": START},
    )

    assert response.status_code == 422


async def test_move_event_requires_auth(client: AsyncClient) -> None:
    token = await _signup(client)
    _, calendar_id = await _make_calendar(client, token)
    created = await client.post(
        f"/api/calendars/{calendar_id}/events",
        headers=_auth_header(token),
        json=_event_payload(),
    )
    event_id = created.json()["id"]

    response = await client.patch(
        f"/api/events/{event_id}",
        json={
            "start_at": "2026-07-02T11:15:00+00:00",
            "end_at": "2026-07-02T12:15:00+00:00",
        },
    )

    assert response.status_code == 401


async def test_move_event_in_others_workspace_returns_404(client: AsyncClient) -> None:
    token_a = await _signup(client)
    token_b = await _signup_second_user(client, token_a)
    _, calendar_id = await _make_calendar(client, token_a)
    created = await client.post(
        f"/api/calendars/{calendar_id}/events",
        headers=_auth_header(token_a),
        json=_event_payload(),
    )
    event_id = created.json()["id"]

    response = await client.patch(
        f"/api/events/{event_id}",
        headers=_auth_header(token_b),
        json={
            "start_at": "2026-07-02T11:15:00+00:00",
            "end_at": "2026-07-02T12:15:00+00:00",
        },
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


async def test_create_event_with_daily_recurrence_and_count(client: AsyncClient) -> None:
    token = await _signup(client)
    _, calendar_id = await _make_calendar(client, token)

    response = await client.post(
        f"/api/calendars/{calendar_id}/events",
        headers=_auth_header(token),
        json=_event_payload(recurrence={"freq": "DAILY", "count": 3}),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["recurrence"] == {
        "freq": "DAILY",
        "interval": 1,
        "by_weekday": None,
        "count": 3,
        "until": None,
    }


async def test_create_event_rejects_count_and_until_together(client: AsyncClient) -> None:
    token = await _signup(client)
    _, calendar_id = await _make_calendar(client, token)

    response = await client.post(
        f"/api/calendars/{calendar_id}/events",
        headers=_auth_header(token),
        json=_event_payload(
            recurrence={"freq": "DAILY", "count": 3, "until": "2026-08-01T00:00:00+00:00"}
        ),
    )

    assert response.status_code == 422


async def test_create_event_rejects_by_weekday_on_non_weekly(client: AsyncClient) -> None:
    token = await _signup(client)
    _, calendar_id = await _make_calendar(client, token)

    response = await client.post(
        f"/api/calendars/{calendar_id}/events",
        headers=_auth_header(token),
        json=_event_payload(recurrence={"freq": "DAILY", "by_weekday": [0, 2]}),
    )

    assert response.status_code == 422


async def test_create_event_rejects_bad_weekday_value(client: AsyncClient) -> None:
    token = await _signup(client)
    _, calendar_id = await _make_calendar(client, token)

    response = await client.post(
        f"/api/calendars/{calendar_id}/events",
        headers=_auth_header(token),
        json=_event_payload(recurrence={"freq": "WEEKLY", "by_weekday": [7]}),
    )

    assert response.status_code == 422


async def test_list_events_expands_daily_recurrence_with_count_limit(
    client: AsyncClient,
) -> None:
    token = await _signup(client)
    workspace_id, calendar_id = await _make_calendar(client, token)

    # Starts Wed 2026-07-01, daily, 3 occurrences: Jul 1, 2, 3.
    await client.post(
        f"/api/calendars/{calendar_id}/events",
        headers=_auth_header(token),
        json=_event_payload(title="Standup", recurrence={"freq": "DAILY", "count": 3}),
    )

    response = await client.get(
        f"{WORKSPACES_URL}/{workspace_id}/events",
        headers=_auth_header(token),
        params={"start": "2026-06-01T00:00:00+00:00", "end": "2026-08-01T00:00:00+00:00"},
    )

    assert response.status_code == 200
    body = response.json()
    starts = sorted(datetime.fromisoformat(e["start_at"]) for e in body)
    assert len(body) == 3
    assert starts == [
        datetime.fromisoformat("2026-07-01T09:00:00+00:00"),
        datetime.fromisoformat("2026-07-02T09:00:00+00:00"),
        datetime.fromisoformat("2026-07-03T09:00:00+00:00"),
    ]
    assert all(e["recurrence"]["freq"] == "DAILY" for e in body)


async def test_list_events_only_includes_occurrences_inside_window(
    client: AsyncClient,
) -> None:
    token = await _signup(client)
    workspace_id, calendar_id = await _make_calendar(client, token)

    await client.post(
        f"/api/calendars/{calendar_id}/events",
        headers=_auth_header(token),
        json=_event_payload(title="Standup", recurrence={"freq": "DAILY", "count": 10}),
    )

    response = await client.get(
        f"{WORKSPACES_URL}/{workspace_id}/events",
        headers=_auth_header(token),
        params={"start": "2026-07-02T00:00:00+00:00", "end": "2026-07-04T00:00:00+00:00"},
    )

    assert response.status_code == 200
    starts = sorted(datetime.fromisoformat(e["start_at"]) for e in response.json())
    assert starts == [
        datetime.fromisoformat("2026-07-02T09:00:00+00:00"),
        datetime.fromisoformat("2026-07-03T09:00:00+00:00"),
    ]


async def test_list_events_expands_weekly_recurrence_on_specific_days(
    client: AsyncClient,
) -> None:
    token = await _signup(client)
    workspace_id, calendar_id = await _make_calendar(client, token)

    # 2026-07-01 is a Wednesday; ask for Mon/Wed/Fri (0, 2, 4) each week.
    await client.post(
        f"/api/calendars/{calendar_id}/events",
        headers=_auth_header(token),
        json=_event_payload(
            title="Gym",
            recurrence={"freq": "WEEKLY", "by_weekday": [0, 2, 4], "until": "2026-07-14T00:00:00+00:00"},
        ),
    )

    response = await client.get(
        f"{WORKSPACES_URL}/{workspace_id}/events",
        headers=_auth_header(token),
        params={"start": "2026-06-01T00:00:00+00:00", "end": "2026-08-01T00:00:00+00:00"},
    )

    assert response.status_code == 200
    starts = sorted(datetime.fromisoformat(e["start_at"]) for e in response.json())
    assert starts == [
        datetime.fromisoformat(d)
        for d in [
            "2026-07-01T09:00:00+00:00",
            "2026-07-03T09:00:00+00:00",
            "2026-07-06T09:00:00+00:00",
            "2026-07-08T09:00:00+00:00",
            "2026-07-10T09:00:00+00:00",
            "2026-07-13T09:00:00+00:00",
        ]
    ]


async def test_delete_recurring_event_removes_whole_series(client: AsyncClient) -> None:
    token = await _signup(client)
    workspace_id, calendar_id = await _make_calendar(client, token)

    created = await client.post(
        f"/api/calendars/{calendar_id}/events",
        headers=_auth_header(token),
        json=_event_payload(recurrence={"freq": "DAILY", "count": 5}),
    )
    event_id = created.json()["id"]

    response = await client.delete(f"/api/events/{event_id}", headers=_auth_header(token))
    assert response.status_code == 204

    listed = await client.get(
        f"{WORKSPACES_URL}/{workspace_id}/events",
        headers=_auth_header(token),
        params={"start": "2026-06-01T00:00:00+00:00", "end": "2026-08-01T00:00:00+00:00"},
    )
    assert listed.json() == []


async def test_bulk_delete_recurring_event_removes_only_selected_occurrence(
    client: AsyncClient,
) -> None:
    token = await _signup(client)
    workspace_id, calendar_id = await _make_calendar(client, token)

    created = await client.post(
        f"/api/calendars/{calendar_id}/events",
        headers=_auth_header(token),
        json=_event_payload(recurrence={"freq": "DAILY", "count": 5}),
    )
    event_id = created.json()["id"]

    response = await client.delete(
        f"/api/events/{event_id}/bulk-delete",
        headers=_auth_header(token),
        params={
            "mode": "this_only",
            "occurrence_start": "2026-07-02T09:00:00+00:00",
        },
    )
    assert response.status_code == 204

    listed = await client.get(
        f"{WORKSPACES_URL}/{workspace_id}/events",
        headers=_auth_header(token),
        params={"start": "2026-06-01T00:00:00+00:00", "end": "2026-08-01T00:00:00+00:00"},
    )
    starts = [datetime.fromisoformat(e["start_at"]) for e in listed.json()]
    assert starts == [
        datetime.fromisoformat("2026-07-01T09:00:00+00:00"),
        datetime.fromisoformat("2026-07-03T09:00:00+00:00"),
        datetime.fromisoformat("2026-07-04T09:00:00+00:00"),
        datetime.fromisoformat("2026-07-05T09:00:00+00:00"),
    ]


async def test_bulk_delete_recurring_event_truncates_future_occurrences(
    client: AsyncClient,
) -> None:
    token = await _signup(client)
    workspace_id, calendar_id = await _make_calendar(client, token)

    created = await client.post(
        f"/api/calendars/{calendar_id}/events",
        headers=_auth_header(token),
        json=_event_payload(recurrence={"freq": "DAILY", "count": 5}),
    )
    event_id = created.json()["id"]

    response = await client.delete(
        f"/api/events/{event_id}/bulk-delete",
        headers=_auth_header(token),
        params={
            "mode": "this_and_future",
            "occurrence_start": "2026-07-03T09:00:00+00:00",
        },
    )
    assert response.status_code == 204

    listed = await client.get(
        f"{WORKSPACES_URL}/{workspace_id}/events",
        headers=_auth_header(token),
        params={"start": "2026-06-01T00:00:00+00:00", "end": "2026-08-01T00:00:00+00:00"},
    )
    starts = [datetime.fromisoformat(e["start_at"]) for e in listed.json()]
    assert starts == [
        datetime.fromisoformat("2026-07-01T09:00:00+00:00"),
        datetime.fromisoformat("2026-07-02T09:00:00+00:00"),
    ]


async def test_update_event_sets_color_override(client: AsyncClient) -> None:
    token = await _signup(client)
    _, calendar_id = await _make_calendar(client, token)
    created = await client.post(
        f"/api/calendars/{calendar_id}/events",
        headers=_auth_header(token),
        json=_event_payload(),
    )
    event_id = created.json()["id"]

    response = await client.patch(
        f"/api/events/{event_id}",
        headers=_auth_header(token),
        json={"start_at": START, "end_at": END, "color": "#16a34a"},
    )

    assert response.status_code == 200
    assert response.json()["color"] == "#16a34a"


async def test_update_event_clears_color_with_explicit_null(client: AsyncClient) -> None:
    token = await _signup(client)
    _, calendar_id = await _make_calendar(client, token)
    created = await client.post(
        f"/api/calendars/{calendar_id}/events",
        headers=_auth_header(token),
        json=_event_payload(color="#16a34a"),
    )
    event_id = created.json()["id"]

    response = await client.patch(
        f"/api/events/{event_id}",
        headers=_auth_header(token),
        json={"start_at": START, "end_at": END, "color": None},
    )

    assert response.status_code == 200
    assert response.json()["color"] is None


async def test_update_event_without_color_keeps_override(client: AsyncClient) -> None:
    token = await _signup(client)
    _, calendar_id = await _make_calendar(client, token)
    created = await client.post(
        f"/api/calendars/{calendar_id}/events",
        headers=_auth_header(token),
        json=_event_payload(color="#16a34a"),
    )
    event_id = created.json()["id"]

    response = await client.patch(
        f"/api/events/{event_id}",
        headers=_auth_header(token),
        json={"start_at": "2026-07-02T11:00:00+00:00", "end_at": "2026-07-02T12:00:00+00:00"},
    )

    assert response.status_code == 200
    assert response.json()["color"] == "#16a34a"


async def test_update_event_rejects_malformed_color(client: AsyncClient) -> None:
    token = await _signup(client)
    _, calendar_id = await _make_calendar(client, token)
    created = await client.post(
        f"/api/calendars/{calendar_id}/events",
        headers=_auth_header(token),
        json=_event_payload(),
    )
    event_id = created.json()["id"]

    response = await client.patch(
        f"/api/events/{event_id}",
        headers=_auth_header(token),
        json={"start_at": START, "end_at": END, "color": "green"},
    )

    assert response.status_code == 422


async def test_update_recurring_event_with_scope_all_shifts_whole_series(
    client: AsyncClient,
) -> None:
    token = await _signup(client)
    workspace_id, calendar_id = await _make_calendar(client, token)
    created = await client.post(
        f"/api/calendars/{calendar_id}/events",
        headers=_auth_header(token),
        json=_event_payload(recurrence={"freq": "DAILY", "count": 3}),
    )
    event_id = created.json()["id"]

    # Retime the second occurrence by +2h and recolor; the whole series follows.
    response = await client.patch(
        f"/api/events/{event_id}",
        headers=_auth_header(token),
        json={
            "start_at": "2026-07-02T11:00:00+00:00",
            "end_at": "2026-07-02T12:30:00+00:00",
            "occurrence_start": "2026-07-02T09:00:00+00:00",
            "color": "#0891b2",
            "scope": "all",
        },
    )

    assert response.status_code == 200
    assert response.json()["id"] == event_id

    listed = await client.get(
        f"{WORKSPACES_URL}/{workspace_id}/events",
        headers=_auth_header(token),
        params={"start": "2026-07-01T00:00:00+00:00", "end": "2026-07-05T00:00:00+00:00"},
    )
    body = listed.json()
    assert [datetime.fromisoformat(event["start_at"]) for event in body] == [
        datetime.fromisoformat("2026-07-01T11:00:00+00:00"),
        datetime.fromisoformat("2026-07-02T11:00:00+00:00"),
        datetime.fromisoformat("2026-07-03T11:00:00+00:00"),
    ]
    assert {event["color"] for event in body} == {"#0891b2"}
    assert [datetime.fromisoformat(event["end_at"]) for event in body][0] == (
        datetime.fromisoformat("2026-07-01T12:30:00+00:00")
    )


async def test_update_recurring_event_this_and_future_splits_series(
    client: AsyncClient,
) -> None:
    token = await _signup(client)
    workspace_id, calendar_id = await _make_calendar(client, token)
    created = await client.post(
        f"/api/calendars/{calendar_id}/events",
        headers=_auth_header(token),
        json=_event_payload(recurrence={"freq": "DAILY", "count": 4}),
    )
    event_id = created.json()["id"]

    response = await client.patch(
        f"/api/events/{event_id}",
        headers=_auth_header(token),
        json={
            "start_at": "2026-07-03T14:00:00+00:00",
            "end_at": "2026-07-03T15:00:00+00:00",
            "occurrence_start": "2026-07-03T09:00:00+00:00",
            "color": "#ea580c",
            "scope": "this_and_future",
        },
    )

    assert response.status_code == 200
    tail_id = response.json()["id"]
    assert tail_id != event_id
    assert response.json()["recurrence"]["freq"] == "DAILY"

    listed = await client.get(
        f"{WORKSPACES_URL}/{workspace_id}/events",
        headers=_auth_header(token),
        params={"start": "2026-07-01T00:00:00+00:00", "end": "2026-07-06T00:00:00+00:00"},
    )
    body = listed.json()
    assert [datetime.fromisoformat(event["start_at"]) for event in body] == [
        datetime.fromisoformat("2026-07-01T09:00:00+00:00"),
        datetime.fromisoformat("2026-07-02T09:00:00+00:00"),
        datetime.fromisoformat("2026-07-03T14:00:00+00:00"),
        datetime.fromisoformat("2026-07-04T14:00:00+00:00"),
    ]
    assert [event["color"] for event in body] == [None, None, "#ea580c", "#ea580c"]


async def test_update_open_recurring_event_this_and_future_keeps_tail_visible(
    client: AsyncClient,
) -> None:
    token = await _signup(client)
    workspace_id, calendar_id = await _make_calendar(client, token)
    created = await client.post(
        f"/api/calendars/{calendar_id}/events",
        headers=_auth_header(token),
        json=_event_payload(recurrence={"freq": "DAILY"}),
    )
    event_id = created.json()["id"]

    response = await client.patch(
        f"/api/events/{event_id}",
        headers=_auth_header(token),
        json={
            "title": "Afternoon standup",
            "start_at": "2026-07-03T14:00:00+00:00",
            "end_at": "2026-07-03T15:00:00+00:00",
            "occurrence_start": "2026-07-03T09:00:00+00:00",
            "scope": "this_and_future",
        },
    )

    assert response.status_code == 200
    assert response.json()["title"] == "Afternoon standup"
    assert response.json()["recurrence"]["until"] is None

    listed = await client.get(
        f"{WORKSPACES_URL}/{workspace_id}/events",
        headers=_auth_header(token),
        params={"start": "2026-07-01T00:00:00+00:00", "end": "2026-07-06T00:00:00+00:00"},
    )
    body = listed.json()
    assert [event["title"] for event in body] == [
        "Standup",
        "Standup",
        "Afternoon standup",
        "Afternoon standup",
        "Afternoon standup",
    ]
    assert [datetime.fromisoformat(event["start_at"]) for event in body] == [
        datetime.fromisoformat("2026-07-01T09:00:00+00:00"),
        datetime.fromisoformat("2026-07-02T09:00:00+00:00"),
        datetime.fromisoformat("2026-07-03T14:00:00+00:00"),
        datetime.fromisoformat("2026-07-04T14:00:00+00:00"),
        datetime.fromisoformat("2026-07-05T14:00:00+00:00"),
    ]


async def test_update_one_off_event_changes_title(client: AsyncClient) -> None:
    token = await _signup(client)
    _, calendar_id = await _make_calendar(client, token)
    created = await client.post(
        f"/api/calendars/{calendar_id}/events",
        headers=_auth_header(token),
        json=_event_payload(),
    )

    response = await client.patch(
        f"/api/events/{created.json()['id']}",
        headers=_auth_header(token),
        json={"title": "Planning", "start_at": START, "end_at": END},
    )

    assert response.status_code == 200
    assert response.json()["title"] == "Planning"


async def test_update_event_rejects_blank_title(client: AsyncClient) -> None:
    token = await _signup(client)
    _, calendar_id = await _make_calendar(client, token)
    created = await client.post(
        f"/api/calendars/{calendar_id}/events",
        headers=_auth_header(token),
        json=_event_payload(),
    )

    response = await client.patch(
        f"/api/events/{created.json()['id']}",
        headers=_auth_header(token),
        json={"title": "   ", "start_at": START, "end_at": END},
    )

    assert response.status_code == 422


async def test_update_recurring_event_this_only_recolors_one_occurrence(
    client: AsyncClient,
) -> None:
    token = await _signup(client)
    workspace_id, calendar_id = await _make_calendar(client, token)
    created = await client.post(
        f"/api/calendars/{calendar_id}/events",
        headers=_auth_header(token),
        json=_event_payload(recurrence={"freq": "DAILY", "count": 3}),
    )
    event_id = created.json()["id"]

    response = await client.patch(
        f"/api/events/{event_id}",
        headers=_auth_header(token),
        json={
            "start_at": "2026-07-02T09:00:00+00:00",
            "end_at": "2026-07-02T10:00:00+00:00",
            "occurrence_start": "2026-07-02T09:00:00+00:00",
            "color": "#7c3aed",
            "scope": "this_only",
        },
    )

    assert response.status_code == 200
    assert response.json()["recurrence"] is None

    listed = await client.get(
        f"{WORKSPACES_URL}/{workspace_id}/events",
        headers=_auth_header(token),
        params={"start": "2026-07-01T00:00:00+00:00", "end": "2026-07-05T00:00:00+00:00"},
    )
    body = listed.json()
    assert [event["color"] for event in body] == [None, "#7c3aed", None]
