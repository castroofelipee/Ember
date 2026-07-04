import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from ember.models import MailAccount, MailProvider

SIGNUP_URL = "/api/auth/signup"
INVITES_URL = "/api/invites"
WORKSPACES_URL = "/api/workspaces"


def _signup_payload(**overrides: object) -> dict:
    payload: dict[str, object] = {
        "email": "ada@example.com",
        "password": "correct horse battery",
        "display_name": "Ada Lovelace",
    }
    payload.update(overrides)
    return payload


def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _signup(client: AsyncClient, **overrides: object) -> str:
    response = await client.post(SIGNUP_URL, json=_signup_payload(**overrides))
    return response.json()["access_token"]


async def _signup_second_user(client: AsyncClient, inviter_token: str) -> str:
    invite = await client.post(INVITES_URL, headers=_auth_header(inviter_token))
    payload = _signup_payload(email="grace@example.com", display_name="Grace Hopper")
    payload["invite_code"] = invite.json()["code"]
    response = await client.post(SIGNUP_URL, json=payload)
    return response.json()["access_token"]


async def _make_workspace(client: AsyncClient, token: str) -> str:
    workspace = await client.post(
        WORKSPACES_URL, headers=_auth_header(token), json={"name": "Home"}
    )
    return workspace.json()["id"]


def _domains_url(workspace_id: str, domain_id: str | None = None) -> str:
    base = f"{WORKSPACES_URL}/{workspace_id}/mail/domains"
    return f"{base}/{domain_id}" if domain_id else base


# --- create -----------------------------------------------------------------


async def test_create_domain_requires_auth(client: AsyncClient) -> None:
    token = await _signup(client)
    workspace_id = await _make_workspace(client, token)

    response = await client.post(
        _domains_url(workspace_id), json={"domain": "example.com"}
    )

    assert response.status_code == 401


async def test_create_domain_returns_201(client: AsyncClient) -> None:
    token = await _signup(client)
    workspace_id = await _make_workspace(client, token)

    response = await client.post(
        _domains_url(workspace_id),
        headers=_auth_header(token),
        json={"domain": "Example.COM"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["domain"] == "example.com"
    assert body["workspace_id"] == workspace_id
    assert body["status"] == "pending"
    assert "id" in body


async def test_create_domain_invalid_returns_422(client: AsyncClient) -> None:
    token = await _signup(client)
    workspace_id = await _make_workspace(client, token)

    response = await client.post(
        _domains_url(workspace_id),
        headers=_auth_header(token),
        json={"domain": "not a domain"},
    )

    assert response.status_code == 422


async def test_create_domain_duplicate_returns_409(client: AsyncClient) -> None:
    token = await _signup(client)
    workspace_id = await _make_workspace(client, token)
    await client.post(
        _domains_url(workspace_id),
        headers=_auth_header(token),
        json={"domain": "example.com"},
    )

    response = await client.post(
        _domains_url(workspace_id),
        headers=_auth_header(token),
        json={"domain": "example.com"},
    )

    assert response.status_code == 409


async def test_create_domain_in_others_workspace_returns_404(client: AsyncClient) -> None:
    token_a = await _signup(client)
    token_b = await _signup_second_user(client, token_a)
    workspace_id = await _make_workspace(client, token_a)

    response = await client.post(
        _domains_url(workspace_id),
        headers=_auth_header(token_b),
        json={"domain": "example.com"},
    )

    assert response.status_code == 404


async def test_create_domain_in_nonexistent_workspace_returns_404(client: AsyncClient) -> None:
    token = await _signup(client)

    response = await client.post(
        _domains_url(str(uuid.uuid4())),
        headers=_auth_header(token),
        json={"domain": "example.com"},
    )

    assert response.status_code == 404


# --- list ---------------------------------------------------------------


async def test_list_domains_requires_auth(client: AsyncClient) -> None:
    token = await _signup(client)
    workspace_id = await _make_workspace(client, token)

    response = await client.get(_domains_url(workspace_id))

    assert response.status_code == 401


async def test_list_domains_returns_own_workspace_domains(client: AsyncClient) -> None:
    token = await _signup(client)
    workspace_id = await _make_workspace(client, token)
    await client.post(
        _domains_url(workspace_id), headers=_auth_header(token), json={"domain": "a.com"}
    )
    await client.post(
        _domains_url(workspace_id), headers=_auth_header(token), json={"domain": "b.com"}
    )

    response = await client.get(_domains_url(workspace_id), headers=_auth_header(token))

    names = [d["domain"] for d in response.json()]
    assert names == ["a.com", "b.com"]


async def test_list_domains_in_others_workspace_returns_404(client: AsyncClient) -> None:
    token_a = await _signup(client)
    token_b = await _signup_second_user(client, token_a)
    workspace_id = await _make_workspace(client, token_a)

    response = await client.get(_domains_url(workspace_id), headers=_auth_header(token_b))

    assert response.status_code == 404


# --- get ------------------------------------------------------------------


async def test_get_domain_returns_200(client: AsyncClient) -> None:
    token = await _signup(client)
    workspace_id = await _make_workspace(client, token)
    created = await client.post(
        _domains_url(workspace_id), headers=_auth_header(token), json={"domain": "example.com"}
    )
    domain_id = created.json()["id"]

    response = await client.get(
        _domains_url(workspace_id, domain_id), headers=_auth_header(token)
    )

    assert response.status_code == 200
    assert response.json()["id"] == domain_id


async def test_get_domain_nonexistent_returns_404(client: AsyncClient) -> None:
    token = await _signup(client)
    workspace_id = await _make_workspace(client, token)

    response = await client.get(
        _domains_url(workspace_id, str(uuid.uuid4())), headers=_auth_header(token)
    )

    assert response.status_code == 404


async def test_get_domain_in_others_workspace_returns_404(client: AsyncClient) -> None:
    token_a = await _signup(client)
    token_b = await _signup_second_user(client, token_a)
    workspace_id = await _make_workspace(client, token_a)
    created = await client.post(
        _domains_url(workspace_id), headers=_auth_header(token_a), json={"domain": "example.com"}
    )
    domain_id = created.json()["id"]

    response = await client.get(
        _domains_url(workspace_id, domain_id), headers=_auth_header(token_b)
    )

    assert response.status_code == 404


# --- update -----------------------------------------------------------------


async def test_update_domain_renames(client: AsyncClient) -> None:
    token = await _signup(client)
    workspace_id = await _make_workspace(client, token)
    created = await client.post(
        _domains_url(workspace_id), headers=_auth_header(token), json={"domain": "example.com"}
    )
    domain_id = created.json()["id"]

    response = await client.patch(
        _domains_url(workspace_id, domain_id),
        headers=_auth_header(token),
        json={"domain": "renamed.com"},
    )

    assert response.status_code == 200
    assert response.json()["domain"] == "renamed.com"


async def test_update_domain_status(client: AsyncClient) -> None:
    token = await _signup(client)
    workspace_id = await _make_workspace(client, token)
    created = await client.post(
        _domains_url(workspace_id), headers=_auth_header(token), json={"domain": "example.com"}
    )
    domain_id = created.json()["id"]

    response = await client.patch(
        _domains_url(workspace_id, domain_id),
        headers=_auth_header(token),
        json={"status": "active"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "active"


async def test_update_domain_invalid_returns_422(client: AsyncClient) -> None:
    token = await _signup(client)
    workspace_id = await _make_workspace(client, token)
    created = await client.post(
        _domains_url(workspace_id), headers=_auth_header(token), json={"domain": "example.com"}
    )
    domain_id = created.json()["id"]

    response = await client.patch(
        _domains_url(workspace_id, domain_id),
        headers=_auth_header(token),
        json={"domain": "not a domain"},
    )

    assert response.status_code == 422


async def test_update_domain_duplicate_returns_409(client: AsyncClient) -> None:
    token = await _signup(client)
    workspace_id = await _make_workspace(client, token)
    await client.post(
        _domains_url(workspace_id), headers=_auth_header(token), json={"domain": "a.com"}
    )
    created_b = await client.post(
        _domains_url(workspace_id), headers=_auth_header(token), json={"domain": "b.com"}
    )
    domain_b_id = created_b.json()["id"]

    response = await client.patch(
        _domains_url(workspace_id, domain_b_id),
        headers=_auth_header(token),
        json={"domain": "a.com"},
    )

    assert response.status_code == 409


async def test_update_domain_nonexistent_returns_404(client: AsyncClient) -> None:
    token = await _signup(client)
    workspace_id = await _make_workspace(client, token)

    response = await client.patch(
        _domains_url(workspace_id, str(uuid.uuid4())),
        headers=_auth_header(token),
        json={"domain": "renamed.com"},
    )

    assert response.status_code == 404


async def test_update_domain_in_others_workspace_returns_404(client: AsyncClient) -> None:
    token_a = await _signup(client)
    token_b = await _signup_second_user(client, token_a)
    workspace_id = await _make_workspace(client, token_a)
    created = await client.post(
        _domains_url(workspace_id), headers=_auth_header(token_a), json={"domain": "example.com"}
    )
    domain_id = created.json()["id"]

    response = await client.patch(
        _domains_url(workspace_id, domain_id),
        headers=_auth_header(token_b),
        json={"domain": "renamed.com"},
    )

    assert response.status_code == 404


# --- delete -----------------------------------------------------------------


async def test_delete_domain_returns_204(client: AsyncClient) -> None:
    token = await _signup(client)
    workspace_id = await _make_workspace(client, token)
    created = await client.post(
        _domains_url(workspace_id), headers=_auth_header(token), json={"domain": "example.com"}
    )
    domain_id = created.json()["id"]

    response = await client.delete(
        _domains_url(workspace_id, domain_id), headers=_auth_header(token)
    )
    assert response.status_code == 204

    follow_up = await client.get(
        _domains_url(workspace_id, domain_id), headers=_auth_header(token)
    )
    assert follow_up.status_code == 404


async def test_delete_domain_nonexistent_returns_404(client: AsyncClient) -> None:
    token = await _signup(client)
    workspace_id = await _make_workspace(client, token)

    response = await client.delete(
        _domains_url(workspace_id, str(uuid.uuid4())), headers=_auth_header(token)
    )

    assert response.status_code == 404


async def test_delete_domain_in_others_workspace_returns_404(client: AsyncClient) -> None:
    token_a = await _signup(client)
    token_b = await _signup_second_user(client, token_a)
    workspace_id = await _make_workspace(client, token_a)
    created = await client.post(
        _domains_url(workspace_id), headers=_auth_header(token_a), json={"domain": "example.com"}
    )
    domain_id = created.json()["id"]

    response = await client.delete(
        _domains_url(workspace_id, domain_id), headers=_auth_header(token_b)
    )

    assert response.status_code == 404


async def test_delete_domain_with_accounts_returns_409(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await _signup(client)
    workspace_id = await _make_workspace(client, token)
    created = await client.post(
        _domains_url(workspace_id), headers=_auth_header(token), json={"domain": "example.com"}
    )
    domain_id = created.json()["id"]

    # Seed a mail account directly (account provisioning goes through
    # `register_mail_account` + Stalwart, out of scope for this router).
    db_session.add(
        MailAccount(
            workspace_id=uuid.UUID(workspace_id),
            domain_id=uuid.UUID(domain_id),
            provider=MailProvider.STALWART,
            provider_account_id="stalwart-1",
            email="ada@example.com",
        )
    )
    await db_session.commit()

    response = await client.delete(
        _domains_url(workspace_id, domain_id), headers=_auth_header(token)
    )

    assert response.status_code == 409
