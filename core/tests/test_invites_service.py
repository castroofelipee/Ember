from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ember.models import Invite
from ember.schemas.auth import SignupRequest
from ember.security import hash_invite_code
from ember.services.auth import EmailAlreadyRegisteredError, InvalidInviteError, signup
from ember.services.invites import create_invite


def _signup_data(**overrides: object) -> SignupRequest:
    data: dict[str, object] = {
        "email": "ada@example.com",
        "password": "correct horse battery",
        "display_name": "Ada Lovelace",
    }
    data.update(overrides)
    return SignupRequest(**data)


async def _create_first_user(db_session: AsyncSession):
    user, _, _ = await signup(db_session, _signup_data())
    return user


async def test_first_signup_needs_no_invite(db_session: AsyncSession) -> None:
    user, _, _ = await signup(db_session, _signup_data())
    assert user.email == "ada@example.com"


async def test_second_signup_without_invite_raises(db_session: AsyncSession) -> None:
    await _create_first_user(db_session)

    with pytest.raises(InvalidInviteError):
        await signup(db_session, _signup_data(email="grace@example.com"))


async def test_second_signup_with_garbage_invite_raises(db_session: AsyncSession) -> None:
    await _create_first_user(db_session)

    with pytest.raises(InvalidInviteError):
        await signup(
            db_session,
            _signup_data(email="grace@example.com", invite_code="not-a-real-code"),
        )


async def test_signup_with_valid_invite_succeeds(db_session: AsyncSession) -> None:
    first_user = await _create_first_user(db_session)
    _, raw_code = await create_invite(db_session, first_user.id)

    user, _, _ = await signup(
        db_session, _signup_data(email="grace@example.com", invite_code=raw_code)
    )
    assert user.email == "grace@example.com"


async def test_valid_invite_is_marked_used(db_session: AsyncSession) -> None:
    first_user = await _create_first_user(db_session)
    invite, raw_code = await create_invite(db_session, first_user.id)

    new_user, _, _ = await signup(
        db_session, _signup_data(email="grace@example.com", invite_code=raw_code)
    )

    invite_row = (
        await db_session.execute(select(Invite).where(Invite.id == invite.id))
    ).scalar_one()
    assert invite_row.used_at is not None
    assert invite_row.used_by_user_id == new_user.id


async def test_invite_cannot_be_used_twice(db_session: AsyncSession) -> None:
    first_user = await _create_first_user(db_session)
    _, raw_code = await create_invite(db_session, first_user.id)

    await signup(db_session, _signup_data(email="grace@example.com", invite_code=raw_code))

    with pytest.raises(InvalidInviteError):
        await signup(db_session, _signup_data(email="ida@example.com", invite_code=raw_code))


async def test_expired_invite_raises(db_session: AsyncSession) -> None:
    first_user = await _create_first_user(db_session)
    invite, raw_code = await create_invite(db_session, first_user.id)
    invite.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    await db_session.flush()

    with pytest.raises(InvalidInviteError):
        await signup(db_session, _signup_data(email="grace@example.com", invite_code=raw_code))


async def test_failed_signup_does_not_burn_the_invite(db_session: AsyncSession) -> None:
    """Duplicate-email failure rolls back the whole transaction, including the
    invite claim — the invite must still be usable afterward."""
    first_user = await _create_first_user(db_session)
    _, raw_code = await create_invite(db_session, first_user.id)

    with pytest.raises(EmailAlreadyRegisteredError):
        await signup(db_session, _signup_data(email="ada@example.com", invite_code=raw_code))

    user, _, _ = await signup(
        db_session, _signup_data(email="grace@example.com", invite_code=raw_code)
    )
    assert user.email == "grace@example.com"


async def test_create_invite_hashes_the_code(db_session: AsyncSession) -> None:
    first_user = await _create_first_user(db_session)
    invite, raw_code = await create_invite(db_session, first_user.id)

    assert invite.code_hash != raw_code
    assert invite.code_hash == hash_invite_code(raw_code)
