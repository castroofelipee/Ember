from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ember.models import Session

SIGNUP_URL = "/api/auth/signup"
LOGIN_URL = "/api/auth/login"
REFRESH_URL = "/api/auth/refresh"


def _signup_payload(**overrides: object) -> dict:
    payload: dict[str, object] = {
        "email": "ada@example.com",
        "password": "correct horse battery",
        "display_name": "Ada Lovelace",
    }
    payload.update(overrides)
    return payload


def _login_payload(**overrides: object) -> dict:
    payload: dict[str, object] = {"email": "ada@example.com", "password": "correct horse battery"}
    payload.update(overrides)
    return payload


async def _signup_and_login(client: AsyncClient) -> None:
    await client.post(SIGNUP_URL, json=_signup_payload())
    await client.post(LOGIN_URL, json=_login_payload())


async def test_refresh_happy_path_returns_new_access_token(client: AsyncClient) -> None:
    await _signup_and_login(client)

    response = await client.post(REFRESH_URL)

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]


async def test_refresh_rotates_cookie_to_a_new_value(client: AsyncClient) -> None:
    await _signup_and_login(client)
    old_cookie_value = client.cookies.get("refresh_token")

    response = await client.post(REFRESH_URL)

    set_cookie = response.headers.get("set-cookie", "")
    assert "refresh_token=" in set_cookie
    assert old_cookie_value not in set_cookie


async def test_refresh_without_cookie_returns_401(client: AsyncClient) -> None:
    response = await client.post(REFRESH_URL)

    assert response.status_code == 401


async def test_refresh_with_garbage_cookie_returns_401(client: AsyncClient) -> None:
    client.cookies.set("refresh_token", "not-a-real-token")

    response = await client.post(REFRESH_URL)

    assert response.status_code == 401


async def test_refresh_reusing_old_cookie_after_rotation_returns_401(
    client: AsyncClient,
) -> None:
    await _signup_and_login(client)

    old_raw_token = client.cookies.get("refresh_token")
    await client.post(REFRESH_URL)  # rotates; httpx client auto-updates its cookie jar

    client.cookies.set("refresh_token", old_raw_token)
    response = await client.post(REFRESH_URL)

    assert response.status_code == 401


async def test_refresh_reuse_revokes_session_so_new_token_also_fails(
    client: AsyncClient,
) -> None:
    await _signup_and_login(client)

    first_token = client.cookies.get("refresh_token")
    await client.post(REFRESH_URL)  # rotates first_token -> second_token
    second_token = client.cookies.get("refresh_token")

    client.cookies.set("refresh_token", first_token)
    await client.post(REFRESH_URL)  # reuse of first_token -> revokes the whole session

    client.cookies.set("refresh_token", second_token)
    response = await client.post(REFRESH_URL)  # second_token itself was never reused,
    assert response.status_code == 401  # but its session is now revoked


async def test_refresh_updates_only_one_session_row(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _signup_and_login(client)  # signup's own session + this login's session

    await client.post(REFRESH_URL)

    sessions = (await db_session.execute(select(Session))).scalars().all()
    assert len(sessions) == 2
