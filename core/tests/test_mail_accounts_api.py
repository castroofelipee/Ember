"""API tests for mail account administration (docs/rfc/mail-module.md §5).

Account creation/deletion calls `MailClient`, so these override the
`_require_mail_client` FastAPI dependency with an in-memory double — no real
Stalwart, no HTTP — the same way `client`/`db_session` override `get_db`.
"""

import uuid

from httpx import AsyncClient

from datetime import UTC, datetime, timedelta

from ember.mail import (
    MailAccountAlreadyExistsError,
    MailConnectionError,
    MailMessageDetail,
    MailMessageSummary,
    MailMessageUpdate,
    MailSendResult,
    MailboxInfo,
)
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
        self,
        *,
        create_error: Exception | None = None,
        delete_error: Exception | None = None,
        send_error: Exception | None = None,
    ) -> None:
        self._create_error = create_error
        self._delete_error = delete_error
        self._send_error = send_error
        self.create_calls: list[tuple[str, str]] = []
        self.delete_calls: list[str] = []
        self.send_calls: list[dict] = []
        self.mark_read_calls: list[tuple[str, str]] = []
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

    async def send_message(self, **kwargs) -> MailSendResult:
        self.send_calls.append(kwargs)
        if self._send_error is not None:
            raise self._send_error
        return MailSendResult(email_id="email-1", submission_id="submission-1")

    async def list_mailboxes(self, *, account_id: str):
        return (
            MailboxInfo(
                id=f"inbox-{account_id}",
                name="Inbox",
                role="inbox",
                total_emails=2,
                total_threads=2,
                unread_emails=1,
                unread_threads=1,
            ),
        )

    async def list_messages(
        self,
        *,
        account_id: str,
        mailbox_role: str,
        limit: int = 50,
        collapse_threads: bool = True,
    ):
        return (
            MailMessageSummary(
                id=f"msg-{account_id}",
                thread_id=f"thread-{account_id}",
                mailbox_ids=(f"{mailbox_role}-{account_id}",),
                keywords=("$seen",) if mailbox_role == "sent" else (),
                has_attachment=False,
                sender=None,
                subject=f"{mailbox_role.title()} message",
                preview="Preview",
                received_at=datetime(2026, 7, 5, 12, 0, tzinfo=UTC),
                size=128,
            ),
        )

    async def get_message(self, *, account_id: str, message_id: str):
        return MailMessageDetail(
            id=message_id,
            thread_id=f"thread-{account_id}",
            mailbox_ids=(f"inbox-{account_id}",),
            keywords=(),
            has_attachment=False,
            sender=None,
            to=(),
            cc=(),
            bcc=(),
            reply_to=(),
            subject="Inbox message",
            preview="Preview",
            received_at=datetime(2026, 7, 5, 12, 0, tzinfo=UTC),
            size=128,
            text_body="Hello from inbox",
            html_body="",
        )

    async def update_message(
        self, *, account_id: str, message_id: str, patch: MailMessageUpdate
    ):
        keywords = ("$seen",) if patch.seen else ()
        mailbox_id = f"{patch.mailbox_role or 'inbox'}-{account_id}"
        return MailMessageDetail(
            id=message_id,
            thread_id=f"thread-{account_id}",
            mailbox_ids=(mailbox_id,),
            keywords=keywords,
            has_attachment=False,
            sender=None,
            to=(),
            cc=(),
            bcc=(),
            reply_to=(),
            subject="Inbox message",
            preview="Preview",
            received_at=datetime(2026, 7, 5, 12, 0, tzinfo=UTC),
            size=128,
            text_body="Hello from inbox",
            html_body="",
        )

    async def mark_mailbox_read(self, *, account_id: str, mailbox_role: str) -> int:
        self.mark_read_calls.append((account_id, mailbox_role))
        # One unread message per account, matching list_mailboxes above.
        return 1

    async def list_thread_messages(self, *, account_id: str, thread_id: str):
        return (
            MailMessageDetail(
                id=f"{thread_id}-1",
                thread_id=thread_id,
                mailbox_ids=(f"inbox-{account_id}",),
                keywords=(),
                has_attachment=False,
                sender=None,
                to=(),
                cc=(),
                bcc=(),
                reply_to=(),
                subject="First",
                preview="Preview 1",
                received_at=datetime(2026, 7, 5, 12, 0, tzinfo=UTC),
                size=128,
                text_body="One",
                html_body="",
            ),
            MailMessageDetail(
                id=f"{thread_id}-2",
                thread_id=thread_id,
                mailbox_ids=(f"inbox-{account_id}",),
                keywords=("$seen",),
                has_attachment=False,
                sender=None,
                to=(),
                cc=(),
                bcc=(),
                reply_to=(),
                subject="Second",
                preview="Preview 2",
                received_at=datetime(2026, 7, 5, 13, 0, tzinfo=UTC),
                size=256,
                text_body="Two",
                html_body="",
            ),
        )


class PaginatedFakeMailClient(MailClient):
    """Mail client double producing `total` distinct, chronologically-ordered
    messages, so offset/limit slicing on the Ember side can be asserted
    precisely — unlike `FakeMailClient`, which always returns exactly one
    message regardless of `limit`."""

    def __init__(self, total: int) -> None:
        self.total = total

    async def health_check(self) -> bool:
        return True

    async def create_account(self, address: str, password: str, *, quota_bytes: int | None = None):
        raise NotImplementedError

    async def set_password(self, account_id: str, password: str) -> None:
        raise NotImplementedError

    async def delete_account(self, account_id: str) -> None:
        raise NotImplementedError

    async def send_message(self, **kwargs) -> MailSendResult:
        raise NotImplementedError

    async def list_mailboxes(self, *, account_id: str):
        return ()

    async def list_messages(
        self,
        *,
        account_id: str,
        mailbox_role: str,
        limit: int = 50,
        collapse_threads: bool = True,
    ):
        count = min(limit, self.total)
        return tuple(
            MailMessageSummary(
                id=f"msg-{i}",
                thread_id=f"thread-{i}",
                mailbox_ids=(f"{mailbox_role}-{account_id}",),
                keywords=(),
                has_attachment=False,
                sender=None,
                subject=f"Message {i}",
                preview="Preview",
                received_at=datetime(2026, 7, 5, 12, 0, tzinfo=UTC) - timedelta(minutes=i),
                size=128,
            )
            for i in range(count)
        )

    async def get_message(self, *, account_id: str, message_id: str):
        raise NotImplementedError

    async def update_message(self, *, account_id: str, message_id: str, patch: MailMessageUpdate):
        raise NotImplementedError

    async def mark_mailbox_read(self, *, account_id: str, mailbox_role: str) -> int:
        raise NotImplementedError

    async def list_thread_messages(self, *, account_id: str, thread_id: str):
        return (
            MailMessageDetail(
                id=f"{thread_id}-1",
                thread_id=thread_id,
                mailbox_ids=(f"inbox-{account_id}",),
                keywords=(),
                has_attachment=False,
                sender=None,
                to=(),
                cc=(),
                bcc=(),
                reply_to=(),
                subject=f"Message {thread_id}",
                preview="Preview",
                received_at=datetime(2026, 7, 5, 12, 0, tzinfo=UTC),
                size=128,
                text_body="Body",
                html_body="",
            ),
        )


def _use_mail_client(mail_client: MailClient) -> None:
    app.dependency_overrides[_require_mail_client] = lambda: mail_client


async def _make_account(
    client: AsyncClient,
    token: str,
    workspace_id: str,
    domain_id: str,
    *,
    email: str = "ada@example.com",
) -> dict:
    response = await client.post(
        _accounts_url(workspace_id),
        headers=_auth_header(token),
        json={"domain_id": domain_id, "email": email},
    )
    return response.json()


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
    assert response.json()["detail"] == "Could not reach the mail server. Please try again."


async def test_create_account_mail_server_rejection_returns_specific_502(client: AsyncClient) -> None:
    token = await _signup(client)
    workspace_id = await _make_workspace(client, token)
    domain_id = await _make_domain(client, token, workspace_id, "example.com")
    _use_mail_client(FakeMailClient(create_error=MailClientError("invalidPatch")))

    response = await client.post(
        _accounts_url(workspace_id),
        headers=_auth_header(token),
        json={"domain_id": domain_id, "email": "ada@example.com"},
    )

    assert response.status_code == 502
    assert response.json()["detail"] == "Mail server rejected the account creation request."


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


# --- send ---------------------------------------------------------------


def _send_url(workspace_id: str, account_id: str) -> str:
    return f"{_accounts_url(workspace_id, account_id)}/messages/send"


def _mailboxes_url(workspace_id: str) -> str:
    return f"{WORKSPACES_URL}/{workspace_id}/mail/mailboxes"


def _messages_url(workspace_id: str) -> str:
    return f"{WORKSPACES_URL}/{workspace_id}/mail/messages"


def _threads_url(workspace_id: str) -> str:
    return f"{WORKSPACES_URL}/{workspace_id}/mail/threads"


def _mark_read_url(workspace_id: str) -> str:
    return f"{WORKSPACES_URL}/{workspace_id}/mail/read"


async def test_send_message_requires_auth(client: AsyncClient) -> None:
    token = await _signup(client)
    workspace_id = await _make_workspace(client, token)
    domain_id = await _make_domain(client, token, workspace_id, "example.com")
    _use_mail_client(FakeMailClient())
    account = await _make_account(client, token, workspace_id, domain_id)

    response = await client.post(
        _send_url(workspace_id, account["id"]),
        json={"to": ["grace@example.com"], "subject": "Hi", "text": "Hello"},
    )

    assert response.status_code == 401


async def test_send_message_returns_submission_ids(client: AsyncClient) -> None:
    token = await _signup(client)
    workspace_id = await _make_workspace(client, token)
    domain_id = await _make_domain(client, token, workspace_id, "example.com")
    mail_client = FakeMailClient()
    _use_mail_client(mail_client)
    account = await _make_account(client, token, workspace_id, domain_id)

    response = await client.post(
        _send_url(workspace_id, account["id"]),
        headers=_auth_header(token),
        json={
            "to": ["Grace@Example.com"],
            "cc": ["team@example.com"],
            "subject": " Hello ",
            "text": "Hello from Ember",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"email_id": "email-1", "submission_id": "submission-1"}
    assert mail_client.send_calls == [
        {
            "account_id": account["provider_account_id"],
            "from_address": "ada@example.com",
            "to": ["grace@example.com"],
            "cc": ["team@example.com"],
            "bcc": [],
            "subject": "Hello",
            "text": "Hello from Ember",
        }
    ]


async def test_send_message_in_others_workspace_returns_404(client: AsyncClient) -> None:
    token_a = await _signup(client)
    token_b = await _signup_second_user(client, token_a)
    workspace_id = await _make_workspace(client, token_a)
    domain_id = await _make_domain(client, token_a, workspace_id, "example.com")
    _use_mail_client(FakeMailClient())
    account = await _make_account(client, token_a, workspace_id, domain_id)

    response = await client.post(
        _send_url(workspace_id, account["id"]),
        headers=_auth_header(token_b),
        json={"to": ["grace@example.com"], "subject": "Hi", "text": "Hello"},
    )

    assert response.status_code == 404


async def test_send_message_provider_rejection_returns_502(client: AsyncClient) -> None:
    token = await _signup(client)
    workspace_id = await _make_workspace(client, token)
    domain_id = await _make_domain(client, token, workspace_id, "example.com")
    mail_client = FakeMailClient()
    _use_mail_client(mail_client)
    account = await _make_account(client, token, workspace_id, domain_id)
    _use_mail_client(FakeMailClient(send_error=MailClientError("submission rejected")))

    response = await client.post(
        _send_url(workspace_id, account["id"]),
        headers=_auth_header(token),
        json={"to": ["grace@example.com"], "subject": "Hi", "text": "Hello"},
    )

    assert response.status_code == 502
    assert response.json()["detail"] == "Outbound mail provider rejected the send request."


# --- inbox --------------------------------------------------------------


async def test_list_mailboxes_returns_workspace_mailboxes(client: AsyncClient) -> None:
    token = await _signup(client)
    workspace_id = await _make_workspace(client, token)
    domain_id = await _make_domain(client, token, workspace_id, "example.com")
    _use_mail_client(FakeMailClient())
    await _make_account(client, token, workspace_id, domain_id)

    response = await client.get(_mailboxes_url(workspace_id), headers=_auth_header(token))

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["role"] == "inbox"
    assert body[0]["account_email"] == "ada@example.com"
    assert body[0]["unread_emails"] == 1


async def test_list_messages_returns_unified_inbox(client: AsyncClient) -> None:
    token = await _signup(client)
    workspace_id = await _make_workspace(client, token)
    domain_id = await _make_domain(client, token, workspace_id, "example.com")
    _use_mail_client(FakeMailClient())
    first = await _make_account(client, token, workspace_id, domain_id)
    second = await _make_account(client, token, workspace_id, domain_id, email="grace@example.com")

    response = await client.get(
        _messages_url(workspace_id),
        headers=_auth_header(token),
    )

    assert response.status_code == 200
    body = response.json()
    items = body["items"]
    assert len(items) == 2
    assert body["has_more"] is False
    assert {items[0]["account_email"], items[1]["account_email"]} == {
        "ada@example.com",
        "grace@example.com",
    }
    assert {items[0]["account_id"], items[1]["account_id"]} == {first["id"], second["id"]}


async def test_list_messages_can_scope_to_one_account(client: AsyncClient) -> None:
    token = await _signup(client)
    workspace_id = await _make_workspace(client, token)
    domain_id = await _make_domain(client, token, workspace_id, "example.com")
    _use_mail_client(FakeMailClient())
    account = await _make_account(client, token, workspace_id, domain_id)
    await _make_account(client, token, workspace_id, domain_id, email="grace@example.com")

    response = await client.get(
        f"{_messages_url(workspace_id)}?account_id={account['id']}&folder=inbox&limit=10",
        headers=_auth_header(token),
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["account_id"] == account["id"]


async def test_list_messages_first_page_has_more(client: AsyncClient) -> None:
    """5 messages, page size 2: the first page is full and there is more."""
    token = await _signup(client)
    workspace_id = await _make_workspace(client, token)
    domain_id = await _make_domain(client, token, workspace_id, "example.com")
    _use_mail_client(FakeMailClient())
    await _make_account(client, token, workspace_id, domain_id)
    _use_mail_client(PaginatedFakeMailClient(total=5))

    response = await client.get(
        f"{_messages_url(workspace_id)}?limit=2",
        headers=_auth_header(token),
    )

    assert response.status_code == 200
    body = response.json()
    assert [item["id"] for item in body["items"]] == ["msg-0", "msg-1"]
    assert body["has_more"] is True


async def test_list_messages_second_page_continues_from_offset(client: AsyncClient) -> None:
    token = await _signup(client)
    workspace_id = await _make_workspace(client, token)
    domain_id = await _make_domain(client, token, workspace_id, "example.com")
    _use_mail_client(FakeMailClient())
    await _make_account(client, token, workspace_id, domain_id)
    _use_mail_client(PaginatedFakeMailClient(total=5))

    response = await client.get(
        f"{_messages_url(workspace_id)}?limit=2&offset=2",
        headers=_auth_header(token),
    )

    assert response.status_code == 200
    body = response.json()
    assert [item["id"] for item in body["items"]] == ["msg-2", "msg-3"]
    assert body["has_more"] is True


async def test_list_messages_last_page_has_no_more(client: AsyncClient) -> None:
    """5 messages, page size 2: the third page holds only the leftover
    message, and there is nothing after it."""
    token = await _signup(client)
    workspace_id = await _make_workspace(client, token)
    domain_id = await _make_domain(client, token, workspace_id, "example.com")
    _use_mail_client(FakeMailClient())
    await _make_account(client, token, workspace_id, domain_id)
    _use_mail_client(PaginatedFakeMailClient(total=5))

    response = await client.get(
        f"{_messages_url(workspace_id)}?limit=2&offset=4",
        headers=_auth_header(token),
    )

    assert response.status_code == 200
    body = response.json()
    assert [item["id"] for item in body["items"]] == ["msg-4"]
    assert body["has_more"] is False


async def test_list_messages_offset_past_the_end_returns_empty_page(client: AsyncClient) -> None:
    token = await _signup(client)
    workspace_id = await _make_workspace(client, token)
    domain_id = await _make_domain(client, token, workspace_id, "example.com")
    _use_mail_client(FakeMailClient())
    await _make_account(client, token, workspace_id, domain_id)
    _use_mail_client(PaginatedFakeMailClient(total=5))

    response = await client.get(
        f"{_messages_url(workspace_id)}?limit=2&offset=10",
        headers=_auth_header(token),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["items"] == []
    assert body["has_more"] is False


async def test_list_threads_returns_paginated_previews(client: AsyncClient) -> None:
    token = await _signup(client)
    workspace_id = await _make_workspace(client, token)
    domain_id = await _make_domain(client, token, workspace_id, "example.com")
    _use_mail_client(FakeMailClient())
    await _make_account(client, token, workspace_id, domain_id)
    _use_mail_client(PaginatedFakeMailClient(total=5))

    first_page = await client.get(
        f"{_threads_url(workspace_id)}?limit=2", headers=_auth_header(token)
    )
    second_page = await client.get(
        f"{_threads_url(workspace_id)}?limit=2&offset=2", headers=_auth_header(token)
    )
    last_page = await client.get(
        f"{_threads_url(workspace_id)}?limit=2&offset=4", headers=_auth_header(token)
    )

    assert [item["thread_id"] for item in first_page.json()["items"]] == ["thread-0", "thread-1"]
    assert first_page.json()["has_more"] is True
    assert [item["thread_id"] for item in second_page.json()["items"]] == ["thread-2", "thread-3"]
    assert second_page.json()["has_more"] is True
    assert [item["thread_id"] for item in last_page.json()["items"]] == ["thread-4"]
    assert last_page.json()["has_more"] is False


async def test_mark_folder_read_requires_auth(client: AsyncClient) -> None:
    token = await _signup(client)
    workspace_id = await _make_workspace(client, token)

    response = await client.post(_mark_read_url(workspace_id))

    assert response.status_code == 401


async def test_mark_folder_read_marks_every_account(client: AsyncClient) -> None:
    token = await _signup(client)
    workspace_id = await _make_workspace(client, token)
    domain_id = await _make_domain(client, token, workspace_id, "example.com")
    mail_client = FakeMailClient()
    _use_mail_client(mail_client)
    await _make_account(client, token, workspace_id, domain_id, email="ada@example.com")
    await _make_account(client, token, workspace_id, domain_id, email="grace@example.com")

    response = await client.post(
        f"{_mark_read_url(workspace_id)}?folder=inbox", headers=_auth_header(token)
    )

    assert response.status_code == 200
    # One unread per account (FakeMailClient), across both provisioned accounts.
    assert response.json() == {"marked": 2}
    assert {role for _, role in mail_client.mark_read_calls} == {"inbox"}
    assert len(mail_client.mark_read_calls) == 2


async def test_mark_folder_read_can_scope_to_one_account(client: AsyncClient) -> None:
    token = await _signup(client)
    workspace_id = await _make_workspace(client, token)
    domain_id = await _make_domain(client, token, workspace_id, "example.com")
    mail_client = FakeMailClient()
    _use_mail_client(mail_client)
    account = await _make_account(client, token, workspace_id, domain_id, email="ada@example.com")
    await _make_account(client, token, workspace_id, domain_id, email="grace@example.com")

    response = await client.post(
        f"{_mark_read_url(workspace_id)}?account_id={account['id']}",
        headers=_auth_header(token),
    )

    assert response.status_code == 200
    assert response.json() == {"marked": 1}
    assert mail_client.mark_read_calls == [(account["provider_account_id"], "inbox")]


async def test_mark_folder_read_in_others_workspace_returns_404(client: AsyncClient) -> None:
    owner_token = await _signup(client)
    workspace_id = await _make_workspace(client, owner_token)
    _use_mail_client(FakeMailClient())
    other_token = await _signup_second_user(client, owner_token)

    response = await client.post(
        _mark_read_url(workspace_id), headers=_auth_header(other_token)
    )

    assert response.status_code == 404


async def test_get_message_returns_detail(client: AsyncClient) -> None:
    token = await _signup(client)
    workspace_id = await _make_workspace(client, token)
    domain_id = await _make_domain(client, token, workspace_id, "example.com")
    _use_mail_client(FakeMailClient())
    account = await _make_account(client, token, workspace_id, domain_id)

    response = await client.get(
        f"{_accounts_url(workspace_id, account['id'])}/messages/message-1",
        headers=_auth_header(token),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == "message-1"
    assert body["account_id"] == account["id"]
    assert body["text_body"] == "Hello from inbox"


async def test_update_message_can_mark_seen_and_move_folder(client: AsyncClient) -> None:
    token = await _signup(client)
    workspace_id = await _make_workspace(client, token)
    domain_id = await _make_domain(client, token, workspace_id, "example.com")
    _use_mail_client(FakeMailClient())
    account = await _make_account(client, token, workspace_id, domain_id)

    response = await client.patch(
        f"{_accounts_url(workspace_id, account['id'])}/messages/message-1",
        headers=_auth_header(token),
        json={"seen": True, "folder": "archive"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == "message-1"
    assert body["keywords"] == ["$seen"]
    assert body["mailbox_ids"] == [f"archive-{account['provider_account_id']}"]


async def test_get_thread_returns_messages_in_thread(client: AsyncClient) -> None:
    token = await _signup(client)
    workspace_id = await _make_workspace(client, token)
    domain_id = await _make_domain(client, token, workspace_id, "example.com")
    _use_mail_client(FakeMailClient())
    account = await _make_account(client, token, workspace_id, domain_id)

    response = await client.get(
        f"{_accounts_url(workspace_id, account['id'])}/threads/thread-1",
        headers=_auth_header(token),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["thread_id"] == "thread-1"
    assert [message["id"] for message in body["messages"]] == ["thread-1-1", "thread-1-2"]


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
