import uuid
from datetime import datetime, timedelta, timezone

import jwt

from ember.config import env

ALGORITHM = "HS256"


def create_access_token(*, user_id: uuid.UUID, session_id: uuid.UUID) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "sid": str(session_id),
        "iat": now,
        "exp": now + timedelta(minutes=env["JWT_ACCESS_TOKEN_TTL_MINUTES"]),
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, env["JWT_SECRET_KEY"], algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict:
    """Raises jwt.PyJWTError (or a subclass) on any invalid/expired token."""
    return jwt.decode(token, env["JWT_SECRET_KEY"], algorithms=[ALGORITHM])
