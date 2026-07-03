from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ember.config import env
from ember.jwt import create_access_token
from ember.models import Credential, RefreshToken, Session, User, UserPreferences
from ember.schemas.auth import LoginRequest, SignupRequest
from ember.security import (
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    verify_password,
    verify_password_timing_safe_dummy,
)


class EmailAlreadyRegisteredError(Exception):
    """Raised when the unique(lower(email)) constraint on `users` rejects a signup."""


class InvalidCredentialsError(Exception):
    """Raised for any login failure — deliberately generic (docs/authentication.md §1.4);
    never reveals whether the email exists or the password was wrong."""


class InvalidRefreshTokenError(Exception):
    """Raised for any refresh failure — missing, expired, revoked-session, or reused
    (docs/authentication.md §1.5). Deliberately generic; the caller never learns which."""


async def signup(session: AsyncSession, data: SignupRequest) -> User:
    user = User(email=data.email, display_name=data.display_name)
    user.credential = Credential(password_hash=hash_password(data.password))
    user.preferences = UserPreferences()

    session.add(user)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise EmailAlreadyRegisteredError(data.email) from exc

    await session.refresh(user)
    return user


async def login(
    session: AsyncSession,
    data: LoginRequest,
    *,
    user_agent: str | None,
    ip_address: str | None,
) -> tuple[str, str]:
    user = (
        await session.execute(
            select(User).where(User.email == data.email).options(selectinload(User.credential))
        )
    ).scalar_one_or_none()

    if user is None or user.credential is None:
        verify_password_timing_safe_dummy(data.password)
        raise InvalidCredentialsError()

    if not verify_password(user.credential.password_hash, data.password):
        raise InvalidCredentialsError()

    now = datetime.now(timezone.utc)
    login_session = Session(
        user_id=user.id,
        user_agent=user_agent,
        ip_address=ip_address,
        last_seen_at=now,
    )
    session.add(login_session)
    await session.flush()

    raw_refresh_token = generate_refresh_token()
    session.add(
        RefreshToken(
            session_id=login_session.id,
            token_hash=hash_refresh_token(raw_refresh_token),
            expires_at=now + timedelta(days=env["REFRESH_TOKEN_TTL_DAYS"]),
        )
    )
    await session.flush()

    access_token = create_access_token(user_id=user.id, session_id=login_session.id)
    return access_token, raw_refresh_token


async def refresh(session: AsyncSession, raw_token: str) -> tuple[str, str]:
    """Validates + rotates a refresh token, returning (access_token, raw_new_refresh_token).

    Single-use: the presented token is marked used and a new one takes its
    place. Presenting an already-used token is treated as theft and revokes
    the whole session (docs/authentication.md §1.5).
    """
    token = (
        await session.execute(
            select(RefreshToken)
            .where(RefreshToken.token_hash == hash_refresh_token(raw_token))
            .options(selectinload(RefreshToken.session))
        )
    ).scalar_one_or_none()

    if token is None:
        raise InvalidRefreshTokenError()

    now = datetime.now(timezone.utc)
    login_session = token.session

    if token.used_at is not None:
        # commit, not flush: this must survive the exception that follows —
        # get_db rolls back the whole request's transaction on error, which
        # would otherwise silently undo the one thing this branch exists to do.
        login_session.revoked_at = now
        await session.commit()
        raise InvalidRefreshTokenError()

    if login_session.revoked_at is not None or token.expires_at <= now:
        raise InvalidRefreshTokenError()

    token.used_at = now
    login_session.last_seen_at = now

    raw_new_token = generate_refresh_token()
    session.add(
        RefreshToken(
            session_id=login_session.id,
            token_hash=hash_refresh_token(raw_new_token),
            expires_at=now + timedelta(days=env["REFRESH_TOKEN_TTL_DAYS"]),
            replaces_id=token.id,
        )
    )
    await session.flush()

    access_token = create_access_token(user_id=login_session.user_id, session_id=login_session.id)
    return access_token, raw_new_token
