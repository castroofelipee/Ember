from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ember.models import Credential, User

REGISTER_URL = "/api/auth/signup"


def _payload(**overrides: object) -> dict:
    payload: dict[str, object] = {
        "email": "ada@example.com",
        "password": "correct horse battery",
        "display_name": "Ada Lovelace",
    }
    payload.update(overrides)
    return payload


async def test_register_happy_path_returns_201(client: AsyncClient) -> None:
    response = await client.post(REGISTER_URL, json=_payload())

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "ada@example.com"
    assert body["display_name"] == "Ada Lovelace"
    assert "id" in body
    assert "created_at" in body


async def test_register_response_never_leaks_password(client: AsyncClient) -> None:
    response = await client.post(REGISTER_URL, json=_payload())

    body_text = response.text
    assert "password" not in body_text
    assert "correct horse battery" not in body_text


async def test_register_persists_hashed_password(client: AsyncClient, db_session: AsyncSession) -> None:
    response = await client.post(REGISTER_URL, json=_payload())
    user_id = response.json()["id"]

    credential = (
        await db_session.execute(select(Credential).where(Credential.user_id == user_id))
    ).scalar_one()
    assert credential.password_hash != "correct horse battery"
    assert credential.password_algorithm == "argon2id"


async def test_register_duplicate_email_returns_409(client: AsyncClient) -> None:
    await client.post(REGISTER_URL, json=_payload())
    response = await client.post(REGISTER_URL, json=_payload(display_name="Someone Else"))

    assert response.status_code == 409


async def test_register_duplicate_email_case_insensitive_returns_409(client: AsyncClient) -> None:
    await client.post(REGISTER_URL, json=_payload(email="ada@example.com"))
    response = await client.post(REGISTER_URL, json=_payload(email="ADA@EXAMPLE.COM"))

    assert response.status_code == 409


async def test_register_only_creates_one_user_on_duplicate(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await client.post(REGISTER_URL, json=_payload())
    await client.post(REGISTER_URL, json=_payload(display_name="Someone Else"))

    users = (
        await db_session.execute(select(User).where(User.email == "ada@example.com"))
    ).scalars().all()
    assert len(users) == 1


async def test_register_invalid_email_returns_422(client: AsyncClient) -> None:
    response = await client.post(REGISTER_URL, json=_payload(email="not-an-email"))

    assert response.status_code == 422


async def test_register_password_too_short_returns_422(client: AsyncClient) -> None:
    response = await client.post(REGISTER_URL, json=_payload(password="short1"))

    assert response.status_code == 422


async def test_register_blank_display_name_returns_422(client: AsyncClient) -> None:
    response = await client.post(REGISTER_URL, json=_payload(display_name="   "))

    assert response.status_code == 422


async def test_register_missing_fields_returns_422(client: AsyncClient) -> None:
    response = await client.post(REGISTER_URL, json={"email": "ada@example.com"})

    assert response.status_code == 422


async def test_register_normalizes_email_before_storing(client: AsyncClient) -> None:
    response = await client.post(REGISTER_URL, json=_payload(email="  Ada@EXAMPLE.com  "))

    assert response.status_code == 201
    assert response.json()["email"] == "ada@example.com"
