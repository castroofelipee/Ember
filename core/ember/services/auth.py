from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ember.models import Credential, User, UserPreferences
from ember.schemas.auth import SignupRequest
from ember.security import hash_password


class EmailAlreadyRegisteredError(Exception):
    """Raised when the unique(lower(email)) constraint on `users` rejects a signup."""


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
