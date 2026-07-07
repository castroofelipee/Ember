import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ember.models import Credential, User
from ember.schemas.auth import SignupRequest
from ember.security import verify_password
from ember.services.auth import EmailAlreadyRegisteredError, signup
from ember.services.invites import create_invite


def _signup_data(**overrides: object) -> SignupRequest:
    data: dict[str, object] = {
        "email": "ada@example.com",
        "password": "correct horse battery",
        "display_name": "Ada Lovelace",
    }
    data.update(overrides)
    return SignupRequest(**data)


async def _invite_code_from(db_session: AsyncSession, inviter_id: uuid.UUID) -> str:
    """Only the first signup in a test is exempt from needing an invite
    (bootstrap) — any signup after that needs a real one."""
    _, raw_code = await create_invite(db_session, inviter_id)
    return raw_code


async def test_signup_creates_user_and_credential(db_session: AsyncSession) -> None:
    """Preferences aren't created at signup — there's no workspace yet to scope
    them to. Each workspace gets its own preferences row when it's created
    (see test_workspaces_service.py)."""
    user, _, _ = await signup(db_session, _signup_data())

    assert user.id is not None
    assert user.email == "ada@example.com"
    assert user.display_name == "Ada Lovelace"

    credential = (
        await db_session.execute(select(Credential).where(Credential.user_id == user.id))
    ).scalar_one()
    assert verify_password(credential.password_hash, "correct horse battery")


async def test_signup_never_stores_plaintext_password(db_session: AsyncSession) -> None:
    user, _, _ = await signup(db_session, _signup_data())

    credential = (
        await db_session.execute(select(Credential).where(Credential.user_id == user.id))
    ).scalar_one()
    assert "correct horse battery" not in credential.password_hash


async def test_signup_duplicate_email_raises(db_session: AsyncSession) -> None:
    first, _, _ = await signup(db_session, _signup_data())
    invite_code = await _invite_code_from(db_session, first.id)

    with pytest.raises(EmailAlreadyRegisteredError):
        await signup(
            db_session, _signup_data(display_name="Someone Else", invite_code=invite_code)
        )


async def test_signup_duplicate_email_case_insensitive_raises(db_session: AsyncSession) -> None:
    first, _, _ = await signup(db_session, _signup_data(email="ada@example.com"))
    invite_code = await _invite_code_from(db_session, first.id)

    with pytest.raises(EmailAlreadyRegisteredError):
        await signup(db_session, _signup_data(email="ADA@Example.com", invite_code=invite_code))


async def test_signup_normalizes_email_case_and_whitespace(db_session: AsyncSession) -> None:
    data = SignupRequest(
        email="  Ada@Example.COM  ",
        password="correct horse battery",
        display_name="Ada Lovelace",
    )
    user, _, _ = await signup(db_session, data)

    assert user.email == "ada@example.com"


async def test_signup_after_failed_duplicate_session_still_usable(db_session: AsyncSession) -> None:
    first, _, _ = await signup(db_session, _signup_data())
    invite_code_1 = await _invite_code_from(db_session, first.id)
    invite_code_2 = await _invite_code_from(db_session, first.id)

    with pytest.raises(EmailAlreadyRegisteredError):
        await signup(db_session, _signup_data(display_name="Dup", invite_code=invite_code_1))

    other, _, _ = await signup(
        db_session, _signup_data(email="grace@example.com", invite_code=invite_code_2)
    )
    assert other.email == "grace@example.com"


async def test_signup_persists_only_one_user_when_duplicate(db_session: AsyncSession) -> None:
    first, _, _ = await signup(db_session, _signup_data())
    invite_code = await _invite_code_from(db_session, first.id)
    await db_session.commit()

    with pytest.raises(EmailAlreadyRegisteredError):
        await signup(db_session, _signup_data(display_name="Dup", invite_code=invite_code))

    count = (
        (await db_session.execute(select(User).where(User.email == "ada@example.com")))
        .scalars()
        .all()
    )
    assert len(count) == 1
