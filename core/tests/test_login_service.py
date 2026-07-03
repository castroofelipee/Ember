import jwt
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ember.config import env
from ember.jwt import ALGORITHM
from ember.models import RefreshToken, Session
from ember.schemas.auth import LoginRequest, SignupRequest
from ember.security import hash_refresh_token
from ember.services.auth import InvalidCredentialsError, login, signup


async def _create_user(db_session: AsyncSession, **overrides: object) -> None:
    data: dict[str, object] = {
        "email": "ada@example.com",
        "password": "correct horse battery",
        "display_name": "Ada Lovelace",
    }
    data.update(overrides)
    await signup(db_session, SignupRequest(**data))
    await db_session.commit()


def _login_data(**overrides: object) -> LoginRequest:
    data: dict[str, object] = {"email": "ada@example.com", "password": "correct horse battery"}
    data.update(overrides)
    return LoginRequest(**data)


async def test_login_returns_access_and_refresh_tokens(db_session: AsyncSession) -> None:
    await _create_user(db_session)

    access_token, refresh_token = await login(
        db_session, _login_data(), user_agent="pytest-agent", ip_address="127.0.0.1"
    )

    assert access_token
    assert refresh_token
    assert access_token != refresh_token


async def test_login_access_token_has_expected_claims(db_session: AsyncSession) -> None:
    await _create_user(db_session)

    access_token, _ = await login(
        db_session, _login_data(), user_agent="pytest-agent", ip_address="127.0.0.1"
    )
    payload = jwt.decode(access_token, env["JWT_SECRET_KEY"], algorithms=[ALGORITHM])

    assert "sub" in payload
    assert "sid" in payload
    assert "exp" in payload
    assert "jti" in payload


async def test_login_creates_session_with_request_metadata(db_session: AsyncSession) -> None:
    await _create_user(db_session)

    _, _ = await login(
        db_session, _login_data(), user_agent="pytest-agent", ip_address="203.0.113.5"
    )

    session_row = (await db_session.execute(select(Session))).scalar_one()
    assert session_row.user_agent == "pytest-agent"
    assert session_row.ip_address == "203.0.113.5"
    assert session_row.revoked_at is None


async def test_login_stores_only_hashed_refresh_token(db_session: AsyncSession) -> None:
    await _create_user(db_session)

    _, raw_refresh_token = await login(
        db_session, _login_data(), user_agent=None, ip_address=None
    )

    refresh_row = (await db_session.execute(select(RefreshToken))).scalar_one()
    assert refresh_row.token_hash != raw_refresh_token
    assert refresh_row.token_hash == hash_refresh_token(raw_refresh_token)
    assert refresh_row.used_at is None


async def test_login_wrong_password_raises(db_session: AsyncSession) -> None:
    await _create_user(db_session)

    with pytest.raises(InvalidCredentialsError):
        await login(
            db_session, _login_data(password="wrong password"), user_agent=None, ip_address=None
        )


async def test_login_unknown_email_raises(db_session: AsyncSession) -> None:
    with pytest.raises(InvalidCredentialsError):
        await login(
            db_session,
            _login_data(email="nobody@example.com"),
            user_agent=None,
            ip_address=None,
        )


async def test_login_is_case_insensitive_on_email(db_session: AsyncSession) -> None:
    await _create_user(db_session)

    access_token, _ = await login(
        db_session, _login_data(email="ADA@Example.COM"), user_agent=None, ip_address=None
    )

    assert access_token


async def test_login_does_not_create_session_on_failure(db_session: AsyncSession) -> None:
    await _create_user(db_session)

    with pytest.raises(InvalidCredentialsError):
        await login(
            db_session, _login_data(password="wrong password"), user_agent=None, ip_address=None
        )

    sessions = (await db_session.execute(select(Session))).scalars().all()
    assert sessions == []
