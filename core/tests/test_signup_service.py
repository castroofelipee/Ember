import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ember.models import Credential, User, UserPreferences
from ember.schemas.auth import SignupRequest
from ember.security import verify_password
from ember.services.auth import EmailAlreadyRegisteredError, signup


def _signup_data(**overrides: object) -> SignupRequest:
    data: dict[str, object] = {
        "email": "ada@example.com",
        "password": "correct horse battery",
        "display_name": "Ada Lovelace",
    }
    data.update(overrides)
    return SignupRequest(**data)


async def test_signup_creates_user_credential_and_preferences(db_session: AsyncSession) -> None:
    user = await signup(db_session, _signup_data())

    assert user.id is not None
    assert user.email == "ada@example.com"
    assert user.display_name == "Ada Lovelace"

    credential = (
        await db_session.execute(select(Credential).where(Credential.user_id == user.id))
    ).scalar_one()
    assert verify_password(credential.password_hash, "correct horse battery")

    preferences = (
        await db_session.execute(select(UserPreferences).where(UserPreferences.user_id == user.id))
    ).scalar_one()
    assert preferences.timezone == "UTC"


async def test_signup_never_stores_plaintext_password(db_session: AsyncSession) -> None:
    user = await signup(db_session, _signup_data())

    credential = (
        await db_session.execute(select(Credential).where(Credential.user_id == user.id))
    ).scalar_one()
    assert "correct horse battery" not in credential.password_hash


async def test_signup_duplicate_email_raises(db_session: AsyncSession) -> None:
    await signup(db_session, _signup_data())

    with pytest.raises(EmailAlreadyRegisteredError):
        await signup(db_session, _signup_data(display_name="Someone Else"))


async def test_signup_duplicate_email_case_insensitive_raises(db_session: AsyncSession) -> None:
    await signup(db_session, _signup_data(email="ada@example.com"))

    with pytest.raises(EmailAlreadyRegisteredError):
        await signup(db_session, _signup_data(email="ADA@Example.com"))


async def test_signup_normalizes_email_case_and_whitespace(db_session: AsyncSession) -> None:
    data = SignupRequest(
        email="  Ada@Example.COM  ",
        password="correct horse battery",
        display_name="Ada Lovelace",
    )
    user = await signup(db_session, data)

    assert user.email == "ada@example.com"


async def test_signup_after_failed_duplicate_session_still_usable(db_session: AsyncSession) -> None:
    await signup(db_session, _signup_data())

    with pytest.raises(EmailAlreadyRegisteredError):
        await signup(db_session, _signup_data(display_name="Dup"))

    other = await signup(db_session, _signup_data(email="grace@example.com"))
    assert other.email == "grace@example.com"


async def test_signup_persists_only_one_user_when_duplicate(db_session: AsyncSession) -> None:
    await signup(db_session, _signup_data())
    await db_session.commit()

    with pytest.raises(EmailAlreadyRegisteredError):
        await signup(db_session, _signup_data(display_name="Dup"))

    count = (
        (await db_session.execute(select(User).where(User.email == "ada@example.com")))
        .scalars()
        .all()
    )
    assert len(count) == 1
