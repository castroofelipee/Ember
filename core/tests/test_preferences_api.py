import uuid

from httpx import AsyncClient

from ember.jwt import create_access_token

SIGNUP_URL = "/api/auth/signup"
LOGOUT_URL = "/api/auth/logout"
PREFERENCES_URL = "/api/users/me/preferences"


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


async def test_get_preferences_requires_auth(client: AsyncClient) -> None:
    response = await client.get(PREFERENCES_URL)

    assert response.status_code == 401


async def test_get_preferences_returns_defaults_after_signup(client: AsyncClient) -> None:
    token = await _signup(client)

    response = await client.get(PREFERENCES_URL, headers=_auth_header(token))

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


async def test_patch_preferences_updates_locale(client: AsyncClient) -> None:
    token = await _signup(client)

    response = await client.patch(
        PREFERENCES_URL, headers=_auth_header(token), json={"locale": "pt-BR"}
    )

    assert response.status_code == 200
    assert response.json()["locale"] == "pt-BR"


async def test_patch_preferences_updates_timezone(client: AsyncClient) -> None:
    token = await _signup(client)

    response = await client.patch(
        PREFERENCES_URL, headers=_auth_header(token), json={"timezone": "America/Sao_Paulo"}
    )

    assert response.status_code == 200
    assert response.json()["timezone"] == "America/Sao_Paulo"


async def test_patch_preferences_partial_update_keeps_other_fields(client: AsyncClient) -> None:
    token = await _signup(client)

    await client.patch(PREFERENCES_URL, headers=_auth_header(token), json={"locale": "fr-FR"})
    response = await client.patch(
        PREFERENCES_URL, headers=_auth_header(token), json={"timezone": "Europe/Paris"}
    )

    body = response.json()
    assert body["locale"] == "fr-FR"
    assert body["timezone"] == "Europe/Paris"


async def test_patch_preferences_updates_work_hours_and_view(client: AsyncClient) -> None:
    token = await _signup(client)

    response = await client.patch(
        PREFERENCES_URL,
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

    response = await client.patch(
        PREFERENCES_URL,
        headers=_auth_header(token),
        json={"work_day_start": 18, "work_day_end": 9},
    )

    assert response.status_code == 422


async def test_patch_preferences_rejects_partial_work_hours_that_invert(client: AsyncClient) -> None:
    """Moving only the start past the stored end is caught in the service so it
    returns 422 rather than a 500 from the DB check constraint."""
    token = await _signup(client)

    response = await client.patch(
        PREFERENCES_URL, headers=_auth_header(token), json={"work_day_start": 20}
    )

    assert response.status_code == 422


async def test_patch_preferences_rejects_bad_time_format(client: AsyncClient) -> None:
    token = await _signup(client)

    response = await client.patch(
        PREFERENCES_URL, headers=_auth_header(token), json={"time_format": "36h"}
    )

    assert response.status_code == 422


async def test_patch_preferences_rejects_out_of_range_week_start(client: AsyncClient) -> None:
    token = await _signup(client)

    response = await client.patch(
        PREFERENCES_URL, headers=_auth_header(token), json={"week_starts_on": 9}
    )

    assert response.status_code == 422


async def test_patch_preferences_invalid_locale_returns_422(client: AsyncClient) -> None:
    token = await _signup(client)

    response = await client.patch(
        PREFERENCES_URL, headers=_auth_header(token), json={"locale": "klingon"}
    )

    assert response.status_code == 422


async def test_patch_preferences_invalid_timezone_returns_422(client: AsyncClient) -> None:
    token = await _signup(client)

    response = await client.patch(
        PREFERENCES_URL, headers=_auth_header(token), json={"timezone": "Mars/Olympus_Mons"}
    )

    assert response.status_code == 422


async def test_preferences_rejects_garbage_token(client: AsyncClient) -> None:
    response = await client.get(PREFERENCES_URL, headers=_auth_header("not-a-real-token"))

    assert response.status_code == 401


async def test_preferences_rejects_token_with_unknown_session(client: AsyncClient) -> None:
    token = create_access_token(user_id=uuid.uuid4(), session_id=uuid.uuid4())

    response = await client.get(PREFERENCES_URL, headers=_auth_header(token))

    assert response.status_code == 401


async def test_preferences_rejects_token_from_revoked_session(client: AsyncClient) -> None:
    """Closes the gap noted after implementing logout: a still-unexpired access
    token must stop working once its session is revoked, not just its refresh
    token — that's exactly what the `sid` claim + this check exist for."""
    token = await _signup(client)

    await client.post(LOGOUT_URL)

    response = await client.get(PREFERENCES_URL, headers=_auth_header(token))
    assert response.status_code == 401


async def test_preferences_rejects_token_with_bad_signature(client: AsyncClient) -> None:
    token = await _signup(client)
    tampered = token[:-1] + ("A" if token[-1] != "A" else "B")

    response = await client.get(PREFERENCES_URL, headers=_auth_header(tampered))

    assert response.status_code == 401


async def test_preferences_only_affects_own_user(client: AsyncClient) -> None:
    token_a = await _signup(client)
    token_b = await _signup_second_user(client, token_a)

    await client.patch(PREFERENCES_URL, headers=_auth_header(token_a), json={"locale": "es-ES"})

    response_b = await client.get(PREFERENCES_URL, headers=_auth_header(token_b))
    assert response_b.json()["locale"] == "en-US"


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
