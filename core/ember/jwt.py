import uuid
from datetime import datetime, timedelta, timezone

import jwt

from ember.config import env

ALGORITHM = "HS256"
OAUTH_STATE_TYP = "oauth_state"
OAUTH_STATE_TTL_MINUTES = 10


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


def create_oauth_state_token(*, user_id: uuid.UUID, provider: str) -> str:
    """Signed CSRF state for an outbound OAuth handshake.

    The provider redirects the *browser* back to Ember, so the callback carries
    no Authorization header and `get_current_user` cannot run there. This token
    is what tells the callback which user started the flow — it is set as an
    httpOnly cookie *and* passed as the `state` parameter, and the callback
    requires both to be present and identical (docs/rfc/github-integration.md).

    A signed token rather than a database row: its only job is to exist for a
    few seconds, and a table for that would need its own cleanup.
    """
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "typ": OAUTH_STATE_TYP,
        "provider": provider,
        "iat": now,
        "exp": now + timedelta(minutes=OAUTH_STATE_TTL_MINUTES),
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, env["JWT_SECRET_KEY"], algorithm=ALGORITHM)


def decode_oauth_state_token(token: str, *, provider: str) -> uuid.UUID:
    """Returns the user id a state token was minted for.

    Raises jwt.PyJWTError on an invalid, expired, or wrong-purpose token — the
    `typ` and `provider` checks stop an access token (or another provider's
    state) from being replayed here.
    """
    payload = jwt.decode(token, env["JWT_SECRET_KEY"], algorithms=[ALGORITHM])
    if payload.get("typ") != OAUTH_STATE_TYP or payload.get("provider") != provider:
        raise jwt.InvalidTokenError("Not an OAuth state token for this provider.")
    try:
        return uuid.UUID(str(payload["sub"]))
    except (KeyError, ValueError) as exc:
        raise jwt.InvalidTokenError("OAuth state token has no valid subject.") from exc
