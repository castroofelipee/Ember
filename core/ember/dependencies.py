import uuid

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from ember.db import get_db
from ember.jwt import decode_access_token
from ember.models import Session, User

bearer_scheme = HTTPBearer(auto_error=True)

_INVALID_TOKEN_ERROR = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Invalid or expired access token.",
)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Validates the bearer JWT and cross-checks its session against revocation
    (docs/authentication.md §4.3 — the `sid` claim exists precisely so sensitive
    endpoints can catch a still-unexpired token from a since-revoked session,
    e.g. one already logged out)."""
    try:
        payload = decode_access_token(credentials.credentials)
    except jwt.PyJWTError as exc:
        raise _INVALID_TOKEN_ERROR from exc

    try:
        session_id = uuid.UUID(str(payload["sid"]))
        user_id = uuid.UUID(str(payload["sub"]))
    except (KeyError, ValueError) as exc:
        raise _INVALID_TOKEN_ERROR from exc

    session_row = await db.get(Session, session_id)
    if session_row is None or session_row.revoked_at is not None:
        raise _INVALID_TOKEN_ERROR

    user = await db.get(User, user_id)
    if user is None:
        raise _INVALID_TOKEN_ERROR

    return user
