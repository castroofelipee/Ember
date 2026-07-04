from httpx import AsyncClient

SIGNUP_URL = "/api/auth/signup"
INVITES_URL = "/api/invites"


def _signup_payload(**overrides: object) -> dict:
    payload: dict[str, object] = {
        "email": "ada@example.com",
        "password": "correct horse battery",
        "display_name": "Ada Lovelace",
    }
    payload.update(overrides)
    return payload


async def _signup(client: AsyncClient, **overrides: object) -> dict:
    response = await client.post(SIGNUP_URL, json=_signup_payload(**overrides))
    return response.json()


def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def test_create_invite_requires_auth(client: AsyncClient) -> None:
    response = await client.post(INVITES_URL)

    assert response.status_code == 401


async def test_create_invite_returns_code_and_expiry(client: AsyncClient) -> None:
    first = await _signup(client)

    response = await client.post(INVITES_URL, headers=_auth_header(first["access_token"]))

    assert response.status_code == 201
    body = response.json()
    assert body["code"]
    assert "expires_at" in body


async def test_signup_without_invite_after_first_user_returns_403(client: AsyncClient) -> None:
    await _signup(client)

    response = await client.post(SIGNUP_URL, json=_signup_payload(email="grace@example.com"))

    assert response.status_code == 403


async def test_signup_with_garbage_invite_returns_403(client: AsyncClient) -> None:
    await _signup(client)

    response = await client.post(
        SIGNUP_URL,
        json=_signup_payload(email="grace@example.com", invite_code="not-a-real-code"),
    )

    assert response.status_code == 403


async def test_signup_with_valid_invite_returns_201(client: AsyncClient) -> None:
    first = await _signup(client)
    invite = await client.post(INVITES_URL, headers=_auth_header(first["access_token"]))

    response = await client.post(
        SIGNUP_URL,
        json=_signup_payload(email="grace@example.com", invite_code=invite.json()["code"]),
    )

    assert response.status_code == 201


async def test_invite_is_single_use_over_http(client: AsyncClient) -> None:
    first = await _signup(client)
    invite = await client.post(INVITES_URL, headers=_auth_header(first["access_token"]))
    code = invite.json()["code"]

    await client.post(
        SIGNUP_URL, json=_signup_payload(email="grace@example.com", invite_code=code)
    )
    response = await client.post(
        SIGNUP_URL, json=_signup_payload(email="ida@example.com", invite_code=code)
    )

    assert response.status_code == 403


async def test_first_signup_needs_no_invite_over_http(client: AsyncClient) -> None:
    response = await client.post(SIGNUP_URL, json=_signup_payload())

    assert response.status_code == 201
