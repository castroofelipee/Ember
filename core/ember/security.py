import hashlib
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

_hasher = PasswordHasher()

# A syntactically valid hash with no matching password, used to keep login's
# response time similar whether or not the email exists (docs/authentication.md
# §1.4 step 2 — avoids leaking account existence via timing).
_DUMMY_PASSWORD_HASH = _hasher.hash(secrets.token_urlsafe(32))


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def verify_password_timing_safe_dummy(password: str) -> None:
    verify_password(_DUMMY_PASSWORD_HASH, password)


def hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def generate_refresh_token() -> str:
    return secrets.token_urlsafe(32)


def hash_refresh_token(raw_token: str) -> str:
    return hash_token(raw_token)


def generate_invite_code() -> str:
    return secrets.token_urlsafe(16)


def hash_invite_code(raw_code: str) -> str:
    return hash_token(raw_code)


def generate_mail_account_password() -> str:
    """A throwaway credential handed to the mail server on account creation.
    Ember never stores mail-server passwords (docs/rfc/mail-module.md §5), so
    this is generated fresh and discarded immediately after the provisioning
    call — nothing persists it."""
    return secrets.token_urlsafe(32)
