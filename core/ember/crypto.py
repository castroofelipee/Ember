from cryptography.fernet import Fernet, InvalidToken

from ember.config import env

__all__ = [
    "SecretDecryptionError",
    "SecretEncryptionUnavailableError",
    "decrypt_secret",
    "encrypt_secret",
]


class SecretEncryptionUnavailableError(Exception):
    """No encryption key is configured. Raised instead of silently storing a
    credential in plaintext."""


class SecretDecryptionError(Exception):
    """The ciphertext could not be decrypted — wrong key, or tampered data."""


def _cipher() -> Fernet:
    key = env["GITHUB_TOKEN_ENCRYPTION_KEY"]
    if not key:
        raise SecretEncryptionUnavailableError(
            "GITHUB_TOKEN_ENCRYPTION_KEY is not set; refusing to handle credentials."
        )
    try:
        return Fernet(key.encode("utf-8"))
    except (ValueError, TypeError) as exc:
        raise SecretEncryptionUnavailableError(
            "GITHUB_TOKEN_ENCRYPTION_KEY is not a valid Fernet key. Generate one with: "
            'python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
        ) from exc


def encrypt_secret(plaintext: str) -> str:
    return _cipher().encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_secret(ciphertext: str) -> str:
    try:
        return _cipher().decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise SecretDecryptionError("Stored credential could not be decrypted.") from exc
