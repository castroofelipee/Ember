from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ember.models import RefreshToken, Session
from ember.security import hash_refresh_token

SIGNUP_URL = "/api/auth/signup"
LOGIN_URL = "/api/auth/login"
LOGOUT_URL = "/api/auth/logout"
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


async def _session_for_token(db_session: AsyncSession, raw_token: str) -> Session:
    token = (
        await db_session.execute(
            select(RefreshToken).where(RefreshToken.token_hash == hash_refresh_token(raw_token))
        )
    ).scalar_one()
    return (
        await db_session.execute(select(Session).where(Session.id == token.session_id))
    ).scalar_one()


async def test_logout_returns_204(client: AsyncClient) -> None:
    await _signup_and_login(client)

    response = await client.post(LOGOUT_URL)

    assert response.status_code == 204
    assert response.text == ""


async def test_logout_clears_the_cookie(client: AsyncClient) -> None:
    await _signup_and_login(client)

    response = await client.post(LOGOUT_URL)

    set_cookie = response.headers.get("set-cookie", "")
    assert "refresh_token=" in set_cookie
    assert 'refresh_token=""' in set_cookie or "max-age=0" in set_cookie.lower()


async def test_logout_revokes_session_in_db(client: AsyncClient, db_session: AsyncSession) -> None:
    await _signup_and_login(client)
    refresh_cookie = client.cookies.get("refresh_token")

    await client.post(LOGOUT_URL)

    session_row = await _session_for_token(db_session, refresh_cookie)
    assert session_row.revoked_at is not None


async def test_refresh_fails_after_logout(client: AsyncClient) -> None:
    await _signup_and_login(client)
    refresh_cookie = client.cookies.get("refresh_token")

    await client.post(LOGOUT_URL)

    # Even presenting the (now-cleared-client-side, but still known) old token
    # must fail once the session is revoked server-side.
    client.cookies.set("refresh_token", refresh_cookie)
    response = await client.post(REFRESH_URL)
    assert response.status_code == 401


async def test_logout_without_cookie_still_returns_204(client: AsyncClient) -> None:
    response = await client.post(LOGOUT_URL)

    assert response.status_code == 204


async def test_logout_with_garbage_cookie_still_returns_204(client: AsyncClient) -> None:
    client.cookies.set("refresh_token", "not-a-real-token")

    response = await client.post(LOGOUT_URL)

    assert response.status_code == 204


async def test_logout_is_idempotent_over_http(client: AsyncClient) -> None:
    await _signup_and_login(client)
    refresh_cookie = client.cookies.get("refresh_token")

    await client.post(LOGOUT_URL)
    client.cookies.set("refresh_token", refresh_cookie)
    response = await client.post(LOGOUT_URL)

    assert response.status_code == 204


async def test_logout_does_not_revoke_other_sessions(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _signup_and_login(client)  # signup's own session + this login's session
    first_cookie = client.cookies.get("refresh_token")

    # A second login (e.g. another device) creates a third session.
    await client.post(LOGIN_URL, json=_login_payload())

    client.cookies.set("refresh_token", first_cookie)
    await client.post(LOGOUT_URL)

    sessions = (await db_session.execute(select(Session))).scalars().all()
    revoked = [s for s in sessions if s.revoked_at is not None]
    still_active = [s for s in sessions if s.revoked_at is None]
    assert len(revoked) == 1
    assert len(still_active) == 2
