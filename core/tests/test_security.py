from ember.security import hash_password, verify_password


def test_hash_password_is_not_plaintext() -> None:
    assert hash_password("correct horse battery") != "correct horse battery"


def test_hash_password_is_salted() -> None:
    assert hash_password("same-password") != hash_password("same-password")


def test_verify_password_accepts_correct_password() -> None:
    hashed = hash_password("correct horse battery")
    assert verify_password(hashed, "correct horse battery") is True


def test_verify_password_rejects_wrong_password() -> None:
    hashed = hash_password("correct horse battery")
    assert verify_password(hashed, "wrong password") is False


def test_verify_password_rejects_garbage_hash() -> None:
    assert verify_password("not-a-real-hash", "whatever") is False
