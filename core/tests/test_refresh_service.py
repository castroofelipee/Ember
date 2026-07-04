from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ember.models import RefreshToken, Session
from ember.schemas.auth import LoginRequest, SignupRequest
from ember.security import hash_refresh_token
from ember.services.auth import InvalidRefreshTokenError, login, refresh, signup


async def _session_for_token(db_session: AsyncSession, raw_token: str) -> Session:
    token = (
        await db_session.execute(
            select(RefreshToken).where(RefreshToken.token_hash == hash_refresh_token(raw_token))
        )
    ).scalar_one()
    return (
        await db_session.execute(select(Session).where(Session.id == token.session_id))
    ).scalar_one()


async def _create_user_and_login(db_session: AsyncSession) -> tuple[str, str]:
    await signup(
        db_session,
        SignupRequest(
            email="ada@example.com",
            password="correct horse battery",
            display_name="Ada Lovelace",
        ),
    )
    access_token, raw_refresh_token = await login(
        db_session,
        LoginRequest(email="ada@example.com", password="correct horse battery"),
        user_agent="pytest-agent",
        ip_address="127.0.0.1",
    )
    await db_session.commit()
    return access_token, raw_refresh_token


async def test_refresh_returns_new_access_and_refresh_tokens(db_session: AsyncSession) -> None:
    _, raw_refresh_token = await _create_user_and_login(db_session)

    new_access_token, new_refresh_token = await refresh(db_session, raw_refresh_token)

    assert new_access_token
    assert new_refresh_token
    assert new_refresh_token != raw_refresh_token


async def test_refresh_marks_old_token_used(db_session: AsyncSession) -> None:
    _, raw_refresh_token = await _create_user_and_login(db_session)

    await refresh(db_session, raw_refresh_token)

    old_token = (
        await db_session.execute(
            select(RefreshToken).where(
                RefreshToken.token_hash == hash_refresh_token(raw_refresh_token)
            )
        )
    ).scalar_one()
    assert old_token.used_at is not None


async def test_refresh_new_token_chains_via_replaces_id(db_session: AsyncSession) -> None:
    _, raw_refresh_token = await _create_user_and_login(db_session)

    _, new_refresh_token = await refresh(db_session, raw_refresh_token)

    old_token = (
        await db_session.execute(
            select(RefreshToken).where(
                RefreshToken.token_hash == hash_refresh_token(raw_refresh_token)
            )
        )
    ).scalar_one()
    new_token = (
        await db_session.execute(
            select(RefreshToken).where(
                RefreshToken.token_hash == hash_refresh_token(new_refresh_token)
            )
        )
    ).scalar_one()
    assert new_token.replaces_id == old_token.id


async def test_refresh_updates_session_last_seen_at(db_session: AsyncSession) -> None:
    _, raw_refresh_token = await _create_user_and_login(db_session)

    session_before = await _session_for_token(db_session, raw_refresh_token)
    original_last_seen_at = session_before.last_seen_at

    await refresh(db_session, raw_refresh_token)

    await db_session.refresh(session_before)
    assert session_before.last_seen_at >= original_last_seen_at


async def test_refresh_unknown_token_raises(db_session: AsyncSession) -> None:
    with pytest.raises(InvalidRefreshTokenError):
        await refresh(db_session, "not-a-real-token")


async def test_refresh_reused_token_raises_and_revokes_session(db_session: AsyncSession) -> None:
    _, raw_refresh_token = await _create_user_and_login(db_session)

    await refresh(db_session, raw_refresh_token)  # first use: rotates fine

    with pytest.raises(InvalidRefreshTokenError):
        await refresh(db_session, raw_refresh_token)  # reuse: theft signal

    session_row = await _session_for_token(db_session, raw_refresh_token)
    assert session_row.revoked_at is not None


async def test_refresh_fails_after_session_revoked_by_reuse(db_session: AsyncSession) -> None:
    _, raw_refresh_token = await _create_user_and_login(db_session)
    _, new_refresh_token = await refresh(db_session, raw_refresh_token)

    with pytest.raises(InvalidRefreshTokenError):
        await refresh(db_session, raw_refresh_token)  # reuse -> revokes session

    # The rotated (otherwise still-valid) token must also stop working once
    # its session is revoked.
    with pytest.raises(InvalidRefreshTokenError):
        await refresh(db_session, new_refresh_token)


async def test_refresh_expired_token_raises(db_session: AsyncSession) -> None:
    _, raw_refresh_token = await _create_user_and_login(db_session)

    token_row = (
        await db_session.execute(
            select(RefreshToken).where(
                RefreshToken.token_hash == hash_refresh_token(raw_refresh_token)
            )
        )
    ).scalar_one()
    token_row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    await db_session.flush()

    with pytest.raises(InvalidRefreshTokenError):
        await refresh(db_session, raw_refresh_token)


async def test_refresh_access_token_carries_correct_session(db_session: AsyncSession) -> None:
    import jwt

    from ember.config import env
    from ember.jwt import ALGORITHM

    _, raw_refresh_token = await _create_user_and_login(db_session)
    session_row = await _session_for_token(db_session, raw_refresh_token)

    new_access_token, _ = await refresh(db_session, raw_refresh_token)
    payload = jwt.decode(new_access_token, env["JWT_SECRET_KEY"], algorithms=[ALGORITHM])

    assert payload["sid"] == str(session_row.id)
    assert payload["sub"] == str(session_row.user_id)
