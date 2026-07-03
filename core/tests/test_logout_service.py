import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ember.models import Session
from ember.schemas.auth import LoginRequest, SignupRequest
from ember.services.auth import InvalidRefreshTokenError, login, logout, refresh, signup


async def _create_user_and_login(db_session: AsyncSession) -> str:
    await signup(
        db_session,
        SignupRequest(
            email="ada@example.com",
            password="correct horse battery",
            display_name="Ada Lovelace",
        ),
    )
    _, raw_refresh_token = await login(
        db_session,
        LoginRequest(email="ada@example.com", password="correct horse battery"),
        user_agent=None,
        ip_address=None,
    )
    await db_session.commit()
    return raw_refresh_token


async def test_logout_revokes_the_session(db_session: AsyncSession) -> None:
    raw_refresh_token = await _create_user_and_login(db_session)

    await logout(db_session, raw_refresh_token)

    session_row = (await db_session.execute(select(Session))).scalar_one()
    assert session_row.revoked_at is not None


async def test_logout_makes_refresh_fail_afterwards(db_session: AsyncSession) -> None:
    raw_refresh_token = await _create_user_and_login(db_session)

    await logout(db_session, raw_refresh_token)
    await db_session.commit()

    with pytest.raises(InvalidRefreshTokenError):
        await refresh(db_session, raw_refresh_token)


async def test_logout_with_none_token_is_a_no_op(db_session: AsyncSession) -> None:
    await _create_user_and_login(db_session)

    await logout(db_session, None)  # must not raise

    session_row = (await db_session.execute(select(Session))).scalar_one()
    assert session_row.revoked_at is None


async def test_logout_with_unknown_token_is_a_no_op(db_session: AsyncSession) -> None:
    await _create_user_and_login(db_session)

    await logout(db_session, "not-a-real-token")  # must not raise

    session_row = (await db_session.execute(select(Session))).scalar_one()
    assert session_row.revoked_at is None


async def test_logout_is_idempotent(db_session: AsyncSession) -> None:
    raw_refresh_token = await _create_user_and_login(db_session)

    await logout(db_session, raw_refresh_token)
    await logout(db_session, raw_refresh_token)  # must not raise the second time either

    session_row = (await db_session.execute(select(Session))).scalar_one()
    assert session_row.revoked_at is not None


async def test_logout_does_not_affect_other_sessions(db_session: AsyncSession) -> None:
    raw_refresh_token_1 = await _create_user_and_login(db_session)
    _, raw_refresh_token_2 = await login(
        db_session,
        LoginRequest(email="ada@example.com", password="correct horse battery"),
        user_agent=None,
        ip_address=None,
    )
    await db_session.commit()

    await logout(db_session, raw_refresh_token_1)

    sessions = (await db_session.execute(select(Session))).scalars().all()
    revoked = [s for s in sessions if s.revoked_at is not None]
    still_active = [s for s in sessions if s.revoked_at is None]
    assert len(revoked) == 1
    assert len(still_active) == 1

    # The other session's refresh token must still work.
    access_token, _ = await refresh(db_session, raw_refresh_token_2)
    assert access_token
