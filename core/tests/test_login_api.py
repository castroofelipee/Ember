from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ember.models import Session

SIGNUP_URL = "/api/auth/signup"
LOGIN_URL = "/api/auth/login"


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


async def test_login_happy_path_returns_access_token(client: AsyncClient) -> None:
    await client.post(SIGNUP_URL, json=_signup_payload())

    response = await client.post(LOGIN_URL, json=_login_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]


async def test_login_sets_httponly_refresh_cookie(client: AsyncClient) -> None:
    await client.post(SIGNUP_URL, json=_signup_payload())

    response = await client.post(LOGIN_URL, json=_login_payload())

    set_cookie = response.headers.get("set-cookie", "")
    assert "refresh_token=" in set_cookie
    assert "httponly" in set_cookie.lower()
    assert "path=/api/auth" in set_cookie.lower()


async def test_login_response_never_leaks_refresh_token_in_body(client: AsyncClient) -> None:
    await client.post(SIGNUP_URL, json=_signup_payload())

    response = await client.post(LOGIN_URL, json=_login_payload())

    assert "refresh" not in response.text.lower()


async def test_login_wrong_password_returns_401(client: AsyncClient) -> None:
    await client.post(SIGNUP_URL, json=_signup_payload())

    response = await client.post(LOGIN_URL, json=_login_payload(password="wrong password"))

    assert response.status_code == 401


async def test_login_unknown_email_returns_401(client: AsyncClient) -> None:
    response = await client.post(LOGIN_URL, json=_login_payload(email="nobody@example.com"))

    assert response.status_code == 401


async def test_login_unknown_email_and_wrong_password_share_same_error(
    client: AsyncClient,
) -> None:
    """Non-enumeration: both failure modes must be indistinguishable to the client."""
    await client.post(SIGNUP_URL, json=_signup_payload())

    wrong_password = await client.post(LOGIN_URL, json=_login_payload(password="wrong password"))
    unknown_email = await client.post(LOGIN_URL, json=_login_payload(email="nobody@example.com"))

    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json() == unknown_email.json()


async def test_login_missing_fields_returns_422(client: AsyncClient) -> None:
    response = await client.post(LOGIN_URL, json={"email": "ada@example.com"})

    assert response.status_code == 422


async def test_login_invalid_email_returns_422(client: AsyncClient) -> None:
    response = await client.post(LOGIN_URL, json=_login_payload(email="not-an-email"))

    assert response.status_code == 422


async def test_login_email_is_case_insensitive(client: AsyncClient) -> None:
    await client.post(SIGNUP_URL, json=_signup_payload())

    response = await client.post(LOGIN_URL, json=_login_payload(email="ADA@EXAMPLE.COM"))

    assert response.status_code == 200


async def test_repeated_logins_create_separate_sessions(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await client.post(SIGNUP_URL, json=_signup_payload())

    await client.post(LOGIN_URL, json=_login_payload())
    await client.post(LOGIN_URL, json=_login_payload())

    sessions = (await db_session.execute(select(Session))).scalars().all()
    assert len(sessions) == 2
