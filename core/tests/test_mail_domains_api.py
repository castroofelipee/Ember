import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from ember.config import env
from ember.mail import MailConnectionError
from ember.mail.client import MailClient
from ember.models import MailAccount, MailProvider

SIGNUP_URL = "/api/auth/signup"
INVITES_URL = "/api/invites"
WORKSPACES_URL = "/api/workspaces"


class FakeMailClient(MailClient):
    """Minimal `MailClient` double for domain-provisioning tests — only
    `ensure_dns_server`/`create_domain` are exercised here; every other
    abstract method is an explicit stub, matching the other fakes in this
    test suite (test_mail_accounts_api.py, test_mail_service.py)."""

    def __init__(self, *, create_domain_error: Exception | None = None) -> None:
        self._create_domain_error = create_domain_error
        self.ensure_dns_server_calls: list[tuple[str, str]] = []
        self.create_domain_calls: list[tuple[str, str | None]] = []

    async def health_check(self) -> bool:
        return True

    async def ensure_dns_server(self, secret: str, *, description: str) -> str:
        self.ensure_dns_server_calls.append((secret, description))
        return "dns-server-1"

    async def create_domain(self, domain: str, *, dns_server_id: str | None = None) -> str:
        self.create_domain_calls.append((domain, dns_server_id))
        if self._create_domain_error is not None:
            raise self._create_domain_error
        return "stalwart-domain-1"

    async def create_account(self, address: str, password: str, *, quota_bytes: int | None = None):
        raise NotImplementedError

    async def set_password(self, account_id: str, password: str) -> None:
        raise NotImplementedError

    async def delete_account(self, account_id: str) -> None:
        raise NotImplementedError

    async def send_message(self, **kwargs):
        raise NotImplementedError

    async def list_mailboxes(self, *, account_id: str):
        raise NotImplementedError

    async def list_messages(self, *, account_id: str, mailbox_role: str, limit: int = 50, collapse_threads: bool = True):
        raise NotImplementedError

    async def get_message(self, *, account_id: str, message_id: str):
        raise NotImplementedError

    async def update_message(self, *, account_id: str, message_id: str, patch):
        raise NotImplementedError

    async def mark_mailbox_read(self, *, account_id: str, mailbox_role: str) -> int:
        raise NotImplementedError

    async def list_thread_messages(self, *, account_id: str, thread_id: str):
        raise NotImplementedError


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


# --- automatic provisioning (Cloudflare/Stalwart) --------------------------


def _patch_mail_client(monkeypatch: pytest.MonkeyPatch, mail_client: MailClient | None) -> None:
    monkeypatch.setattr("ember.routers.mail.get_mail_client", lambda: mail_client)


def _patch_verify_dns_defer(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    """Swap `verify_domain_dns.defer_async` for a recorder — no Procrastinate
    schema exists against the test DB (docs/background-jobs.md: it's installed
    by an Alembic migration, not the SQLAlchemy `create_all` these tests use),
    so actually deferring would fail for reasons unrelated to what these tests
    check."""
    calls: list[dict] = []

    async def fake_defer_async(**kwargs: object) -> None:
        calls.append(kwargs)

    monkeypatch.setattr("ember.routers.mail.verify_domain_dns.defer_async", fake_defer_async)
    return calls


async def test_create_domain_without_mail_configured_stays_ember_only(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_mail_client(monkeypatch, None)
    token = await _signup(client)
    workspace_id = await _make_workspace(client, token)

    response = await client.post(
        _domains_url(workspace_id), headers=_auth_header(token), json={"domain": "example.com"}
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "pending"
    assert body["stalwart_domain_id"] is None
    assert body["provisioning_error"] is None


async def test_create_domain_with_cloudflare_configured_provisions_on_mail_server(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(env, "CLOUDFLARE_API_TOKEN", "cf-token")
    mail_client = FakeMailClient()
    _patch_mail_client(monkeypatch, mail_client)
    deferred = _patch_verify_dns_defer(monkeypatch)
    token = await _signup(client)
    workspace_id = await _make_workspace(client, token)

    response = await client.post(
        _domains_url(workspace_id), headers=_auth_header(token), json={"domain": "example.com"}
    )

    assert response.status_code == 201
    body = response.json()
    assert body["stalwart_domain_id"] == "stalwart-domain-1"
    assert body["provisioning_error"] is None
    assert mail_client.ensure_dns_server_calls == [("cf-token", "ember-cloudflare")]
    assert mail_client.create_domain_calls == [("example.com", "dns-server-1")]
    assert deferred == [{"domain_id": body["id"]}]


async def test_create_domain_provisioning_failure_still_returns_201_with_error(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(env, "CLOUDFLARE_API_TOKEN", "cf-token")
    mail_client = FakeMailClient(create_domain_error=MailConnectionError("unreachable"))
    _patch_mail_client(monkeypatch, mail_client)
    deferred = _patch_verify_dns_defer(monkeypatch)
    token = await _signup(client)
    workspace_id = await _make_workspace(client, token)

    response = await client.post(
        _domains_url(workspace_id), headers=_auth_header(token), json={"domain": "example.com"}
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "pending"
    assert body["stalwart_domain_id"] is None
    assert body["provisioning_error"] == "unreachable"
    assert deferred == []  # never queue verification for a provision that never succeeded


async def test_manual_retry_provisions_a_previously_unconfigured_domain(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Domain created before Cloudflare was configured (the common real-world
    # sequence: add the domain, then set CLOUDFLARE_API_TOKEN, then retry).
    _patch_mail_client(monkeypatch, None)
    token = await _signup(client)
    workspace_id = await _make_workspace(client, token)
    created = await client.post(
        _domains_url(workspace_id), headers=_auth_header(token), json={"domain": "example.com"}
    )
    domain_id = created.json()["id"]

    monkeypatch.setitem(env, "CLOUDFLARE_API_TOKEN", "cf-token")
    mail_client = FakeMailClient()
    _patch_mail_client(monkeypatch, mail_client)
    _patch_verify_dns_defer(monkeypatch)

    response = await client.post(
        f"{_domains_url(workspace_id, domain_id)}/provision", headers=_auth_header(token)
    )

    assert response.status_code == 200
    assert response.json()["stalwart_domain_id"] == "stalwart-domain-1"
    assert mail_client.create_domain_calls == [("example.com", "dns-server-1")]


async def test_manual_retry_requires_auth(client: AsyncClient) -> None:
    token = await _signup(client)
    workspace_id = await _make_workspace(client, token)
    created = await client.post(
        _domains_url(workspace_id), headers=_auth_header(token), json={"domain": "example.com"}
    )
    domain_id = created.json()["id"]

    response = await client.post(f"{_domains_url(workspace_id, domain_id)}/provision")

    assert response.status_code == 401


async def test_manual_retry_nonexistent_domain_returns_404(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_mail_client(monkeypatch, None)
    token = await _signup(client)
    workspace_id = await _make_workspace(client, token)

    response = await client.post(
        f"{_domains_url(workspace_id, str(uuid.uuid4()))}/provision", headers=_auth_header(token)
    )

    assert response.status_code == 404
