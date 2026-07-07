import uuid

from httpx import AsyncClient

from ember.jwt import create_access_token

SIGNUP_URL = "/api/auth/signup"
LOGOUT_URL = "/api/auth/logout"
WORKSPACES_URL = "/api/workspaces"


def _signup_payload(**overrides: object) -> dict:
    payload: dict[str, object] = {
        "email": "ada@example.com",
        "password": "correct horse battery",
        "display_name": "Ada Lovelace",
    }
    payload.update(overrides)
    return payload


async def _signup(client: AsyncClient) -> str:
    response = await client.post(SIGNUP_URL, json=_signup_payload())
    return response.json()["access_token"]


def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _create_workspace(client: AsyncClient, token: str, name: str = "Home") -> str:
    response = await client.post(WORKSPACES_URL, headers=_auth_header(token), json={"name": name})
    return response.json()["id"]


def _preferences_url(workspace_id: str) -> str:
    return f"{WORKSPACES_URL}/{workspace_id}/preferences"


async def _signup_second_user(client: AsyncClient, inviter_token: str) -> str:
    invite = await client.post(
        "/api/invites", headers={"Authorization": f"Bearer {inviter_token}"}
    )
    response = await client.post(
        SIGNUP_URL,
        json=_signup_payload(
            email="grace@example.com",
            display_name="Grace Hopper",
            invite_code=invite.json()["code"],
        ),
    )
    return response.json()["access_token"]


async def test_get_preferences_requires_auth(client: AsyncClient) -> None:
    token = await _signup(client)
    workspace_id = await _create_workspace(client, token)

    response = await client.get(_preferences_url(workspace_id))

    assert response.status_code == 401


async def test_get_preferences_returns_defaults_after_workspace_created(
    client: AsyncClient,
) -> None:
    token = await _signup(client)
    workspace_id = await _create_workspace(client, token)

    response = await client.get(_preferences_url(workspace_id), headers=_auth_header(token))

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "locale": "en-US",
        "timezone": "UTC",
        "week_starts_on": 0,
        "work_day_start": 9,
        "work_day_end": 17,
        "time_format": "12h",
    }


async def test_get_preferences_for_nonexistent_workspace_returns_404(client: AsyncClient) -> None:
    token = await _signup(client)

    response = await client.get(
        _preferences_url("00000000-0000-0000-0000-000000000000"), headers=_auth_header(token)
    )

    assert response.status_code == 404


async def test_get_preferences_for_others_workspace_returns_404(client: AsyncClient) -> None:
    token_a = await _signup(client)
    token_b = await _signup_second_user(client, token_a)
    workspace_id = await _create_workspace(client, token_a)

    response = await client.get(_preferences_url(workspace_id), headers=_auth_header(token_b))

    assert response.status_code == 404


async def test_patch_preferences_updates_locale(client: AsyncClient) -> None:
    token = await _signup(client)
    workspace_id = await _create_workspace(client, token)

    response = await client.patch(
        _preferences_url(workspace_id), headers=_auth_header(token), json={"locale": "pt-BR"}
    )

    assert response.status_code == 200
    assert response.json()["locale"] == "pt-BR"


async def test_patch_preferences_updates_timezone(client: AsyncClient) -> None:
    token = await _signup(client)
    workspace_id = await _create_workspace(client, token)

    response = await client.patch(
        _preferences_url(workspace_id),
        headers=_auth_header(token),
        json={"timezone": "America/Sao_Paulo"},
    )

    assert response.status_code == 200
    assert response.json()["timezone"] == "America/Sao_Paulo"


async def test_patch_preferences_partial_update_keeps_other_fields(client: AsyncClient) -> None:
    token = await _signup(client)
    workspace_id = await _create_workspace(client, token)

    await client.patch(
        _preferences_url(workspace_id), headers=_auth_header(token), json={"locale": "fr-FR"}
    )
    response = await client.patch(
        _preferences_url(workspace_id),
        headers=_auth_header(token),
        json={"timezone": "Europe/Paris"},
    )

    body = response.json()
    assert body["locale"] == "fr-FR"
    assert body["timezone"] == "Europe/Paris"


async def test_patch_preferences_updates_work_hours_and_view(client: AsyncClient) -> None:
    token = await _signup(client)
    workspace_id = await _create_workspace(client, token)

    response = await client.patch(
        _preferences_url(workspace_id),
        headers=_auth_header(token),
        json={
            "week_starts_on": 1,
            "work_day_start": 8,
            "work_day_end": 18,
            "time_format": "24h",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["week_starts_on"] == 1
    assert body["work_day_start"] == 8
    assert body["work_day_end"] == 18
    assert body["time_format"] == "24h"


async def test_patch_preferences_rejects_work_end_before_start(client: AsyncClient) -> None:
    token = await _signup(client)
    workspace_id = await _create_workspace(client, token)

    response = await client.patch(
        _preferences_url(workspace_id),
        headers=_auth_header(token),
        json={"work_day_start": 18, "work_day_end": 9},
    )

    assert response.status_code == 422


async def test_patch_preferences_rejects_partial_work_hours_that_invert(
    client: AsyncClient,
) -> None:
    """Moving only the start past the stored end is caught in the service so it
    returns 422 rather than a 500 from the DB check constraint."""
    token = await _signup(client)
    workspace_id = await _create_workspace(client, token)

    response = await client.patch(
        _preferences_url(workspace_id), headers=_auth_header(token), json={"work_day_start": 20}
    )

    assert response.status_code == 422


async def test_patch_preferences_rejects_bad_time_format(client: AsyncClient) -> None:
    token = await _signup(client)
    workspace_id = await _create_workspace(client, token)

    response = await client.patch(
        _preferences_url(workspace_id), headers=_auth_header(token), json={"time_format": "36h"}
    )

    assert response.status_code == 422


async def test_patch_preferences_rejects_out_of_range_week_start(client: AsyncClient) -> None:
    token = await _signup(client)
    workspace_id = await _create_workspace(client, token)

    response = await client.patch(
        _preferences_url(workspace_id), headers=_auth_header(token), json={"week_starts_on": 9}
    )

    assert response.status_code == 422


async def test_patch_preferences_invalid_locale_returns_422(client: AsyncClient) -> None:
    token = await _signup(client)
    workspace_id = await _create_workspace(client, token)

    response = await client.patch(
        _preferences_url(workspace_id), headers=_auth_header(token), json={"locale": "klingon"}
    )

    assert response.status_code == 422


async def test_patch_preferences_invalid_timezone_returns_422(client: AsyncClient) -> None:
    token = await _signup(client)
    workspace_id = await _create_workspace(client, token)

    response = await client.patch(
        _preferences_url(workspace_id),
        headers=_auth_header(token),
        json={"timezone": "Mars/Olympus_Mons"},
    )

    assert response.status_code == 422


async def test_patch_preferences_for_others_workspace_returns_404(client: AsyncClient) -> None:
    token_a = await _signup(client)
    token_b = await _signup_second_user(client, token_a)
    workspace_id = await _create_workspace(client, token_a)

    response = await client.patch(
        _preferences_url(workspace_id), headers=_auth_header(token_b), json={"locale": "es-ES"}
    )

    assert response.status_code == 404


async def test_preferences_rejects_garbage_token(client: AsyncClient) -> None:
    token = await _signup(client)
    workspace_id = await _create_workspace(client, token)

    response = await client.get(
        _preferences_url(workspace_id), headers=_auth_header("not-a-real-token")
    )

    assert response.status_code == 401


async def test_preferences_rejects_token_with_unknown_session(client: AsyncClient) -> None:
    token = await _signup(client)
    workspace_id = await _create_workspace(client, token)
    unknown_token = create_access_token(user_id=uuid.uuid4(), session_id=uuid.uuid4())

    response = await client.get(_preferences_url(workspace_id), headers=_auth_header(unknown_token))

    assert response.status_code == 401


async def test_preferences_rejects_token_from_revoked_session(client: AsyncClient) -> None:
    """Closes the gap noted after implementing logout: a still-unexpired access
    token must stop working once its session is revoked, not just its refresh
    token — that's exactly what the `sid` claim + this check exist for."""
    token = await _signup(client)
    workspace_id = await _create_workspace(client, token)

    await client.post(LOGOUT_URL)

    response = await client.get(_preferences_url(workspace_id), headers=_auth_header(token))
    assert response.status_code == 401


async def test_preferences_rejects_token_with_bad_signature(client: AsyncClient) -> None:
    token = await _signup(client)
    workspace_id = await _create_workspace(client, token)
    tampered = token[:-1] + ("A" if token[-1] != "A" else "B")

    response = await client.get(_preferences_url(workspace_id), headers=_auth_header(tampered))

    assert response.status_code == 401


async def test_preferences_only_affects_own_user(client: AsyncClient) -> None:
    token_a = await _signup(client)
    token_b = await _signup_second_user(client, token_a)
    workspace_a = await _create_workspace(client, token_a)
    workspace_b = await _create_workspace(client, token_b)

    await client.patch(
        _preferences_url(workspace_a), headers=_auth_header(token_a), json={"locale": "es-ES"}
    )

    response_b = await client.get(_preferences_url(workspace_b), headers=_auth_header(token_b))
    assert response_b.json()["locale"] == "en-US"


async def test_preferences_are_independent_per_workspace(client: AsyncClient) -> None:
    """The core behavior this feature adds: one workspace's schedule/settings
    changes must not leak into another workspace owned by the same user."""
    token = await _signup(client)
    home_id = await _create_workspace(client, token, name="Home")
    work_id = await _create_workspace(client, token, name="Work")

    await client.patch(
        _preferences_url(home_id),
        headers=_auth_header(token),
        json={"locale": "fr-FR", "work_day_start": 6, "work_day_end": 14},
    )

    home_response = await client.get(_preferences_url(home_id), headers=_auth_header(token))
    work_response = await client.get(_preferences_url(work_id), headers=_auth_header(token))

    assert home_response.json()["locale"] == "fr-FR"
    assert home_response.json()["work_day_start"] == 6
    assert work_response.json()["locale"] == "en-US"
    assert work_response.json()["work_day_start"] == 9
