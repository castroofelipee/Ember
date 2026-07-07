import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ember.config import env
from ember.jwt import create_access_token
from ember.models import Credential, Invite, RefreshToken, Session, User
from ember.schemas.auth import LoginRequest, SignupRequest
from ember.security import (
    generate_refresh_token,
    hash_invite_code,
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


class InvalidInviteError(Exception):
    """Raised when the signup invite code is missing, unknown, expired, or already used.

    Registration is closed to the internet by default — this is the gate."""


async def _consume_invite(session: AsyncSession, raw_code: str) -> uuid.UUID:
    """Atomically claims an invite: a plain SELECT-then-UPDATE would leave a race
    window where two concurrent signups could both see the same unused invite.
    UPDATE ... WHERE used_at IS NULL ... RETURNING closes that in one statement.
    """
    now = datetime.now(timezone.utc)
    result = await session.execute(
        update(Invite)
        .where(
            Invite.code_hash == hash_invite_code(raw_code),
            Invite.used_at.is_(None),
            Invite.expires_at > now,
        )
        .values(used_at=now)
        .returning(Invite.id)
    )
    invite_id = result.scalar_one_or_none()
    if invite_id is None:
        raise InvalidInviteError()
    return invite_id


async def _open_session_and_issue_tokens(
    session: AsyncSession,
    user: User,
    *,
    user_agent: str | None,
    ip_address: str | None,
) -> tuple[str, str]:
    """Shared by login and signup (signup auto-logs-in — see docs/authentication.md
    deviation note: no email verification exists in this codebase, so there is no
    "unverified" state to hold the account in before granting access)."""
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


async def signup(
    session: AsyncSession,
    data: SignupRequest,
    *,
    user_agent: str | None = None,
    ip_address: str | None = None,
) -> tuple[User, str, str]:
    """Creates the account and immediately opens a session (see
    `_open_session_and_issue_tokens`). Returns (user, access_token, raw_refresh_token).

    Requires a valid invite — registration is closed to the internet by
    default. Exception: while the users table is empty, signup is allowed
    without one, purely to bootstrap the very first account (nobody exists
    yet to have issued an invite). That window closes for good the moment
    the first account is created.

    Claiming the invite and creating the user happen in the same
    transaction: if the email turns out to be a duplicate, the IntegrityError
    rollback below undoes the invite claim too, so a failed signup never
    burns an invite.
    """
    is_first_user = (await session.execute(select(func.count()).select_from(User))).scalar_one() == 0

    invite_id = None
    if not is_first_user:
        if not data.invite_code:
            raise InvalidInviteError()
        invite_id = await _consume_invite(session, data.invite_code)

    user = User(email=data.email, display_name=data.display_name)
    user.credential = Credential(password_hash=hash_password(data.password))

    session.add(user)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise EmailAlreadyRegisteredError(data.email) from exc

    if invite_id is not None:
        await session.execute(
            update(Invite).where(Invite.id == invite_id).values(used_by_user_id=user.id)
        )
    await session.refresh(user)
    access_token, raw_refresh_token = await _open_session_and_issue_tokens(
        session, user, user_agent=user_agent, ip_address=ip_address
    )
    return user, access_token, raw_refresh_token


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

    return await _open_session_and_issue_tokens(
        session, user, user_agent=user_agent, ip_address=ip_address
    )


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


async def logout(session: AsyncSession, raw_token: str | None) -> None:
    """Revokes the session tied to the presented refresh token, if any.

    Deliberately a no-op — never an error — when the cookie is missing or
    doesn't match anything: logout must be safe to call repeatedly or with a
    stale/already-cleared cookie (docs/authentication.md §1.6), and revealing
    "that token wasn't valid" gains an attacker nothing worth leaking.
    """
    if raw_token is None:
        return

    token = (
        await session.execute(
            select(RefreshToken)
            .where(RefreshToken.token_hash == hash_refresh_token(raw_token))
            .options(selectinload(RefreshToken.session))
        )
    ).scalar_one_or_none()

    if token is None:
        return

    if token.session.revoked_at is None:
        token.session.revoked_at = datetime.now(timezone.utc)
        await session.flush()
