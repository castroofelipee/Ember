"""API tests for mail account administration (docs/rfc/mail-module.md §5).

Account creation/deletion calls `MailClient`, so these override the
`_require_mail_client` FastAPI dependency with an in-memory double — no real
Stalwart, no HTTP — the same way `client`/`db_session` override `get_db`.
"""

import uuid

from httpx import AsyncClient

from ember.mail import MailAccountAlreadyExistsError, MailConnectionError
from ember.main import app
from ember.mail.client import MailAccount as ProvisionedAccount
from ember.mail.client import MailClient, MailClientError
from ember.routers.mail import _require_mail_client

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


async def _make_domain(client: AsyncClient, token: str, workspace_id: str, domain: str) -> str:
    response = await client.post(
        f"{WORKSPACES_URL}/{workspace_id}/mail/domains",
        headers=_auth_header(token),
        json={"domain": domain},
    )
    return response.json()["id"]


def _accounts_url(workspace_id: str, account_id: str | None = None) -> str:
    base = f"{WORKSPACES_URL}/{workspace_id}/mail/accounts"
    return f"{base}/{account_id}" if account_id else base


class FakeMailClient(MailClient):
    """In-memory `MailClient` double, mirroring the one in test_mail_service.py."""

    def __init__(
        self, *, create_error: Exception | None = None, delete_error: Exception | None = None
    ) -> None:
        self._create_error = create_error
        self._delete_error = delete_error
        self.create_calls: list[tuple[str, str]] = []
        self.delete_calls: list[str] = []
        self._next_id = 1

    async def health_check(self) -> bool:
        return True

    async def create_account(
        self, address: str, password: str, *, quota_bytes: int | None = None
    ) -> ProvisionedAccount:
        self.create_calls.append((address, password))
        if self._create_error is not None:
            raise self._create_error
        account_id = str(self._next_id)
        self._next_id += 1
        return ProvisionedAccount(id=account_id, address=address)

    async def set_password(self, account_id: str, password: str) -> None:
        raise NotImplementedError

    async def delete_account(self, account_id: str) -> None:
        self.delete_calls.append(account_id)
        if self._delete_error is not None:
            raise self._delete_error


def _use_mail_client(mail_client: MailClient) -> None:
    app.dependency_overrides[_require_mail_client] = lambda: mail_client


# --- create -------------------------------------------------------------


async def test_create_account_requires_auth(client: AsyncClient) -> None:
    token = await _signup(client)
    workspace_id = await _make_workspace(client, token)
    domain_id = await _make_domain(client, token, workspace_id, "example.com")

    response = await client.post(
        _accounts_url(workspace_id), json={"domain_id": domain_id, "email": "ada@example.com"}
    )

    assert response.status_code == 401


async def test_create_account_without_mail_configured_returns_503(client: AsyncClient) -> None:
    token = await _signup(client)
    workspace_id = await _make_workspace(client, token)
    domain_id = await _make_domain(client, token, workspace_id, "example.com")

    # No override: the real get_mail_client() factory returns None in tests
    # (MAIL_ENABLED defaults to False).
    response = await client.post(
        _accounts_url(workspace_id),
        headers=_auth_header(token),
        json={"domain_id": domain_id, "email": "ada@example.com"},
    )

    assert response.status_code == 503


async def test_create_account_returns_201(client: AsyncClient) -> None:
    token = await _signup(client)
    workspace_id = await _make_workspace(client, token)
    domain_id = await _make_domain(client, token, workspace_id, "example.com")
    mail_client = FakeMailClient()
    _use_mail_client(mail_client)

    response = await client.post(
        _accounts_url(workspace_id),
        headers=_auth_header(token),
        json={"domain_id": domain_id, "email": "Ada@Example.com", "display_name": "Ada"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "ada@example.com"
    assert body["display_name"] == "Ada"
    assert body["workspace_id"] == workspace_id
    assert body["domain_id"] == domain_id
    assert body["provider"] == "stalwart"
    assert body["provider_account_id"] == "1"
    assert body["status"] == "active"
    assert mail_client.create_calls[0][0] == "ada@example.com"


async def test_create_account_nonexistent_domain_returns_404(client: AsyncClient) -> None:
    token = await _signup(client)
    workspace_id = await _make_workspace(client, token)
    _use_mail_client(FakeMailClient())

    response = await client.post(
        _accounts_url(workspace_id),
        headers=_auth_header(token),
        json={"domain_id": str(uuid.uuid4()), "email": "ada@example.com"},
    )

    assert response.status_code == 404


async def test_create_account_email_not_on_domain_returns_422(client: AsyncClient) -> None:
    token = await _signup(client)
    workspace_id = await _make_workspace(client, token)
    domain_id = await _make_domain(client, token, workspace_id, "example.com")
    _use_mail_client(FakeMailClient())

    response = await client.post(
        _accounts_url(workspace_id),
        headers=_auth_header(token),
        json={"domain_id": domain_id, "email": "ada@other.com"},
    )

    assert response.status_code == 422


async def test_create_account_already_exists_on_mail_server_returns_409(
    client: AsyncClient,
) -> None:
    token = await _signup(client)
    workspace_id = await _make_workspace(client, token)
    domain_id = await _make_domain(client, token, workspace_id, "example.com")
    _use_mail_client(
        FakeMailClient(create_error=MailAccountAlreadyExistsError("already exists"))
    )

    response = await client.post(
        _accounts_url(workspace_id),
        headers=_auth_header(token),
        json={"domain_id": domain_id, "email": "ada@example.com"},
    )

    assert response.status_code == 409


async def test_create_account_mail_server_unreachable_returns_502(client: AsyncClient) -> None:
    token = await _signup(client)
    workspace_id = await _make_workspace(client, token)
    domain_id = await _make_domain(client, token, workspace_id, "example.com")
    _use_mail_client(FakeMailClient(create_error=MailConnectionError("unreachable")))

    response = await client.post(
        _accounts_url(workspace_id),
        headers=_auth_header(token),
        json={"domain_id": domain_id, "email": "ada@example.com"},
    )

    assert response.status_code == 502


async def test_create_account_in_others_workspace_returns_404(client: AsyncClient) -> None:
    token_a = await _signup(client)
    token_b = await _signup_second_user(client, token_a)
    workspace_id = await _make_workspace(client, token_a)
    domain_id = await _make_domain(client, token_a, workspace_id, "example.com")
    _use_mail_client(FakeMailClient())

    response = await client.post(
        _accounts_url(workspace_id),
        headers=_auth_header(token_b),
        json={"domain_id": domain_id, "email": "ada@example.com"},
    )

    assert response.status_code == 404


# --- list -----------------------------------------------------------------


async def test_list_accounts_requires_auth(client: AsyncClient) -> None:
    token = await _signup(client)
    workspace_id = await _make_workspace(client, token)

    response = await client.get(_accounts_url(workspace_id))

    assert response.status_code == 401


async def test_list_accounts_returns_own_workspace_accounts(client: AsyncClient) -> None:
    token = await _signup(client)
    workspace_id = await _make_workspace(client, token)
    domain_id = await _make_domain(client, token, workspace_id, "example.com")
    _use_mail_client(FakeMailClient())
    await client.post(
        _accounts_url(workspace_id),
        headers=_auth_header(token),
        json={"domain_id": domain_id, "email": "ada@example.com"},
    )
    await client.post(
        _accounts_url(workspace_id),
        headers=_auth_header(token),
        json={"domain_id": domain_id, "email": "support@example.com"},
    )

    response = await client.get(_accounts_url(workspace_id), headers=_auth_header(token))

    emails = [a["email"] for a in response.json()]
    assert emails == ["ada@example.com", "support@example.com"]


async def test_list_accounts_in_others_workspace_returns_404(client: AsyncClient) -> None:
    token_a = await _signup(client)
    token_b = await _signup_second_user(client, token_a)
    workspace_id = await _make_workspace(client, token_a)

    response = await client.get(_accounts_url(workspace_id), headers=_auth_header(token_b))

    assert response.status_code == 404


# --- update -----------------------------------------------------------------


async def test_update_account_display_name(client: AsyncClient) -> None:
    token = await _signup(client)
    workspace_id = await _make_workspace(client, token)
    domain_id = await _make_domain(client, token, workspace_id, "example.com")
    _use_mail_client(FakeMailClient())
    created = await client.post(
        _accounts_url(workspace_id),
        headers=_auth_header(token),
        json={"domain_id": domain_id, "email": "ada@example.com"},
    )
    account_id = created.json()["id"]

    response = await client.patch(
        _accounts_url(workspace_id, account_id),
        headers=_auth_header(token),
        json={"display_name": "Ada L."},
    )

    assert response.status_code == 200
    assert response.json()["display_name"] == "Ada L."


async def test_update_account_status_suspends(client: AsyncClient) -> None:
    token = await _signup(client)
    workspace_id = await _make_workspace(client, token)
    domain_id = await _make_domain(client, token, workspace_id, "example.com")
    _use_mail_client(FakeMailClient())
    created = await client.post(
        _accounts_url(workspace_id),
        headers=_auth_header(token),
        json={"domain_id": domain_id, "email": "ada@example.com"},
    )
    account_id = created.json()["id"]

    response = await client.patch(
        _accounts_url(workspace_id, account_id),
        headers=_auth_header(token),
        json={"status": "suspended"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "suspended"


async def test_update_account_nonexistent_returns_404(client: AsyncClient) -> None:
    token = await _signup(client)
    workspace_id = await _make_workspace(client, token)

    response = await client.patch(
        _accounts_url(workspace_id, str(uuid.uuid4())),
        headers=_auth_header(token),
        json={"display_name": "Nobody"},
    )

    assert response.status_code == 404


async def test_update_account_in_others_workspace_returns_404(client: AsyncClient) -> None:
    token_a = await _signup(client)
    token_b = await _signup_second_user(client, token_a)
    workspace_id = await _make_workspace(client, token_a)
    domain_id = await _make_domain(client, token_a, workspace_id, "example.com")
    _use_mail_client(FakeMailClient())
    created = await client.post(
        _accounts_url(workspace_id),
        headers=_auth_header(token_a),
        json={"domain_id": domain_id, "email": "ada@example.com"},
    )
    account_id = created.json()["id"]

    response = await client.patch(
        _accounts_url(workspace_id, account_id),
        headers=_auth_header(token_b),
        json={"display_name": "Snooping"},
    )

    assert response.status_code == 404


# --- delete -----------------------------------------------------------------


async def test_delete_account_returns_204(client: AsyncClient) -> None:
    token = await _signup(client)
    workspace_id = await _make_workspace(client, token)
    domain_id = await _make_domain(client, token, workspace_id, "example.com")
    mail_client = FakeMailClient()
    _use_mail_client(mail_client)
    created = await client.post(
        _accounts_url(workspace_id),
        headers=_auth_header(token),
        json={"domain_id": domain_id, "email": "ada@example.com"},
    )
    account_id = created.json()["id"]

    response = await client.delete(
        _accounts_url(workspace_id, account_id), headers=_auth_header(token)
    )

    assert response.status_code == 204
    assert mail_client.delete_calls == ["1"]

    listed = await client.get(_accounts_url(workspace_id), headers=_auth_header(token))
    assert listed.json() == []


async def test_delete_account_without_mail_configured_returns_503(client: AsyncClient) -> None:
    token = await _signup(client)
    workspace_id = await _make_workspace(client, token)
    domain_id = await _make_domain(client, token, workspace_id, "example.com")
    _use_mail_client(FakeMailClient())
    created = await client.post(
        _accounts_url(workspace_id),
        headers=_auth_header(token),
        json={"domain_id": domain_id, "email": "ada@example.com"},
    )
    account_id = created.json()["id"]
    app.dependency_overrides.pop(_require_mail_client, None)

    response = await client.delete(
        _accounts_url(workspace_id, account_id), headers=_auth_header(token)
    )

    assert response.status_code == 503


async def test_delete_account_mail_server_failure_returns_502_and_keeps_row(
    client: AsyncClient,
) -> None:
    token = await _signup(client)
    workspace_id = await _make_workspace(client, token)
    domain_id = await _make_domain(client, token, workspace_id, "example.com")
    _use_mail_client(FakeMailClient())
    created = await client.post(
        _accounts_url(workspace_id),
        headers=_auth_header(token),
        json={"domain_id": domain_id, "email": "ada@example.com"},
    )
    account_id = created.json()["id"]

    _use_mail_client(FakeMailClient(delete_error=MailClientError("mail server refused")))
    response = await client.delete(
        _accounts_url(workspace_id, account_id), headers=_auth_header(token)
    )
    assert response.status_code == 502

    listed = await client.get(_accounts_url(workspace_id), headers=_auth_header(token))
    assert [a["id"] for a in listed.json()] == [account_id]


async def test_delete_account_nonexistent_returns_404(client: AsyncClient) -> None:
    token = await _signup(client)
    workspace_id = await _make_workspace(client, token)
    _use_mail_client(FakeMailClient())

    response = await client.delete(
        _accounts_url(workspace_id, str(uuid.uuid4())), headers=_auth_header(token)
    )

    assert response.status_code == 404


async def test_delete_account_in_others_workspace_returns_404(client: AsyncClient) -> None:
    token_a = await _signup(client)
    token_b = await _signup_second_user(client, token_a)
    workspace_id = await _make_workspace(client, token_a)
    domain_id = await _make_domain(client, token_a, workspace_id, "example.com")
    _use_mail_client(FakeMailClient())
    created = await client.post(
        _accounts_url(workspace_id),
        headers=_auth_header(token_a),
        json={"domain_id": domain_id, "email": "ada@example.com"},
    )
    account_id = created.json()["id"]

    response = await client.delete(
        _accounts_url(workspace_id, account_id), headers=_auth_header(token_b)
    )

    assert response.status_code == 404
