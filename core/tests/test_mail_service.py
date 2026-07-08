"""Service tests for the mail domain model (docs/rfc/mail-module.md §5).

`register_mail_account` now integrates with `MailClient`: it must provision an
account on the mail server before writing anything to Ember's database, and
compensate (delete the mail-server account) if the local write fails after
that. These tests exercise that contract with a `FakeMailClient` test double —
no real Stalwart, no HTTP — while everything else still runs against a real
Postgres via `db_session`.
"""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ember.mail import MailAccountAlreadyExistsError, MailClientError, MailConnectionError
from ember.mail.client import MailAccount as ProvisionedAccount
from ember.mail.client import MailMessageDetail, MailMessageSummary, MailboxInfo
from ember.mail.client import MailSendResult
from ember.mail.client import MailMessageUpdate
from ember.mail.client import MailClient
from ember.models import (
    MailAccount,
    MailAccountStatus,
    MailDomain,
    MailDomainStatus,
    MailProvider,
)
from ember.schemas.auth import SignupRequest
from ember.schemas.mail import (
    MailAccountRegisterRequest,
    MailAccountUpdateRequest,
    MailDomainCreateRequest,
)
from ember.schemas.workspaces import WorkspaceCreateRequest
from ember.services.auth import signup
from ember.services.invites import create_invite
from ember.services.mail import (
    EmailAlreadyExistsError,
    EmailDomainMismatchError,
    MailDomainNotFoundError,
    create_mail_domain,
    delete_mail_account,
    get_mail_account,
    get_mail_domain,
    list_mail_accounts,
    list_mail_domains,
    register_mail_account,
    update_mail_account,
)
from ember.services.workspaces import create_workspace


class FakeMailClient(MailClient):
    """In-memory `MailClient` double: no network, no Stalwart. Configurable to
    fail `create_account`/`delete_account`, and records every call so tests
    can assert on the compensating-delete behavior."""

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

    async def send_message(self, **kwargs) -> MailSendResult:
        return MailSendResult(email_id="email-1", submission_id="submission-1")

    async def list_mailboxes(self, *, account_id: str):
        return (
            MailboxInfo(
                id=f"inbox-{account_id}",
                name="Inbox",
                role="inbox",
                total_emails=0,
                total_threads=0,
                unread_emails=0,
                unread_threads=0,
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
                keywords=(),
                has_attachment=False,
                sender=None,
                subject="Inbox message",
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
    ) -> MailMessageDetail:
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


async def _create_user(db_session: AsyncSession, *, inviter_id=None, **overrides: object):
    data: dict[str, object] = {
        "email": "ada@example.com",
        "password": "correct horse battery",
        "display_name": "Ada Lovelace",
    }
    data.update(overrides)
    if inviter_id is not None:
        _, data["invite_code"] = await create_invite(db_session, inviter_id)
    user, _, _ = await signup(db_session, SignupRequest(**data))
    return user


async def _workspace(db_session: AsyncSession):
    user = await _create_user(db_session)
    workspace = await create_workspace(
        db_session, user.id, WorkspaceCreateRequest(name="Home")
    )
    return user, workspace


# --- MailDomain -----------------------------------------------------------


async def test_create_mail_domain_defaults_to_pending(db_session: AsyncSession) -> None:
    _, workspace = await _workspace(db_session)

    domain = await create_mail_domain(
        db_session, workspace.id, MailDomainCreateRequest(domain="example.com")
    )

    assert domain.workspace_id == workspace.id
    assert domain.domain == "example.com"
    assert domain.status == MailDomainStatus.PENDING


async def test_create_mail_domain_normalizes_case(db_session: AsyncSession) -> None:
    _, workspace = await _workspace(db_session)

    domain = await create_mail_domain(
        db_session, workspace.id, MailDomainCreateRequest(domain="  Example.COM  ")
    )
    assert domain.domain == "example.com"


async def test_domain_is_globally_unique(db_session: AsyncSession) -> None:
    _, workspace = await _workspace(db_session)
    await create_mail_domain(
        db_session, workspace.id, MailDomainCreateRequest(domain="example.com")
    )
    db_session.add(MailDomain(workspace_id=workspace.id, domain="example.com"))
    with pytest.raises(Exception):  # unique index on lower(domain)
        await db_session.flush()


def test_domain_request_rejects_garbage() -> None:
    with pytest.raises(ValueError):
        MailDomainCreateRequest(domain="not a domain")


async def test_list_mail_domains_scoped_to_workspace(db_session: AsyncSession) -> None:
    user_a, ws_a = await _workspace(db_session)
    user_b = await _create_user(
        db_session, inviter_id=user_a.id, email="grace@example.com", display_name="Grace"
    )
    ws_b = await create_workspace(db_session, user_b.id, WorkspaceCreateRequest(name="Work"))

    await create_mail_domain(db_session, ws_a.id, MailDomainCreateRequest(domain="a.com"))
    await create_mail_domain(db_session, ws_b.id, MailDomainCreateRequest(domain="b.com"))

    listed = await list_mail_domains(db_session, ws_a.id)
    assert [d.domain for d in listed] == ["a.com"]


# --- MailAccount ----------------------------------------------------------


async def _domain(db_session: AsyncSession, workspace, name="example.com") -> MailDomain:
    return await create_mail_domain(
        db_session, workspace.id, MailDomainCreateRequest(domain=name)
    )


async def test_register_provisions_on_mail_server_then_persists(
    db_session: AsyncSession,
) -> None:
    user, workspace = await _workspace(db_session)
    domain = await _domain(db_session, workspace)
    mail_client = FakeMailClient()

    account = await register_mail_account(
        db_session,
        workspace.id,
        MailAccountRegisterRequest(
            domain_id=domain.id,
            email="ada@example.com",
            user_id=user.id,
            display_name="Ada",
        ),
        mail_client,
    )

    # The mail server was asked to create the account with a real (if
    # throwaway) password, never an empty or fixed one.
    assert mail_client.create_calls == [("ada@example.com", mail_client.create_calls[0][1])]
    assert mail_client.create_calls[0][1]  # non-empty generated password
    assert mail_client.delete_calls == []  # no compensation needed on success

    assert account.workspace_id == workspace.id
    assert account.domain_id == domain.id
    assert account.user_id == user.id
    assert account.email == "ada@example.com"
    assert account.display_name == "Ada"
    assert account.provider == MailProvider.STALWART
    assert account.provider_account_id == "1"  # FakeMailClient's first issued id
    assert account.status == MailAccountStatus.ACTIVE


async def test_register_shared_account_has_no_user(db_session: AsyncSession) -> None:
    _, workspace = await _workspace(db_session)
    domain = await _domain(db_session, workspace)
    mail_client = FakeMailClient()

    account = await register_mail_account(
        db_session,
        workspace.id,
        MailAccountRegisterRequest(domain_id=domain.id, email="support@example.com"),
        mail_client,
    )
    assert account.user_id is None


async def test_register_normalizes_email_case(db_session: AsyncSession) -> None:
    _, workspace = await _workspace(db_session)
    domain = await _domain(db_session, workspace)
    mail_client = FakeMailClient()

    account = await register_mail_account(
        db_session,
        workspace.id,
        MailAccountRegisterRequest(domain_id=domain.id, email="Ada@Example.com"),
        mail_client,
    )
    assert account.email == "ada@example.com"
    # The mail server must see the same normalized address Ember stores.
    assert mail_client.create_calls[0][0] == "ada@example.com"


async def test_register_rejects_domain_from_other_workspace(
    db_session: AsyncSession,
) -> None:
    user_a, ws_a = await _workspace(db_session)
    user_b = await _create_user(
        db_session, inviter_id=user_a.id, email="grace@example.com", display_name="Grace"
    )
    ws_b = await create_workspace(db_session, user_b.id, WorkspaceCreateRequest(name="Work"))
    domain_b = await _domain(db_session, ws_b, name="b.com")
    mail_client = FakeMailClient()

    with pytest.raises(MailDomainNotFoundError):
        await register_mail_account(
            db_session,
            ws_a.id,
            MailAccountRegisterRequest(domain_id=domain_b.id, email="x@b.com"),
            mail_client,
        )

    # Validation failed before any provider call was attempted.
    assert mail_client.create_calls == []


async def test_register_rejects_email_not_on_domain(db_session: AsyncSession) -> None:
    _, workspace = await _workspace(db_session)
    domain = await _domain(db_session, workspace, name="example.com")
    mail_client = FakeMailClient()

    with pytest.raises(EmailDomainMismatchError):
        await register_mail_account(
            db_session,
            workspace.id,
            MailAccountRegisterRequest(domain_id=domain.id, email="ada@other.com"),
            mail_client,
        )

    assert mail_client.create_calls == []


async def test_register_mail_server_unavailable_persists_nothing(
    db_session: AsyncSession,
) -> None:
    _, workspace = await _workspace(db_session)
    domain = await _domain(db_session, workspace)
    mail_client = FakeMailClient(create_error=MailConnectionError("mail server unreachable"))

    with pytest.raises(MailConnectionError):
        await register_mail_account(
            db_session,
            workspace.id,
            MailAccountRegisterRequest(domain_id=domain.id, email="ada@example.com"),
            mail_client,
        )

    listed = await list_mail_accounts(db_session, workspace.id)
    assert listed == []
    # Nothing was created on the mail server either, so nothing to compensate.
    assert mail_client.delete_calls == []


async def test_register_email_already_exists_on_mail_server(
    db_session: AsyncSession,
) -> None:
    _, workspace = await _workspace(db_session)
    domain = await _domain(db_session, workspace)
    mail_client = FakeMailClient(
        create_error=MailAccountAlreadyExistsError("ada@example.com already exists")
    )

    with pytest.raises(MailAccountAlreadyExistsError):
        await register_mail_account(
            db_session,
            workspace.id,
            MailAccountRegisterRequest(domain_id=domain.id, email="ada@example.com"),
            mail_client,
        )

    listed = await list_mail_accounts(db_session, workspace.id)
    assert listed == []
    assert mail_client.delete_calls == []


async def test_register_db_failure_after_provisioning_deletes_from_mail_server(
    db_session: AsyncSession,
) -> None:
    """Simulates 'DB fails after Stalwart succeeded': pre-seed a row that
    collides on the unique email index, so `session.flush()` raises during
    `register_mail_account` after the fake provider already 'created' the
    account. The service must compensate by calling `delete_account`."""
    _, workspace = await _workspace(db_session)
    domain = await _domain(db_session, workspace)

    db_session.add(
        MailAccount(
            workspace_id=workspace.id,
            domain_id=domain.id,
            provider=MailProvider.STALWART,
            provider_account_id="pre-existing",
            email="ada@example.com",
        )
    )
    await db_session.flush()

    mail_client = FakeMailClient()

    with pytest.raises(Exception):  # unique index on lower(email) violated
        await register_mail_account(
            db_session,
            workspace.id,
            MailAccountRegisterRequest(domain_id=domain.id, email="ada@example.com"),
            mail_client,
        )

    # The provider call happened (that's the account we must clean up)...
    assert len(mail_client.create_calls) == 1
    # ...and the compensating delete used exactly the id the provider returned.
    assert mail_client.delete_calls == ["1"]


async def test_register_compensating_delete_failure_does_not_hide_db_error(
    db_session: AsyncSession,
) -> None:
    """If the compensating `delete_account` itself fails, the original DB error
    must still propagate — losing visibility into the real failure would be
    worse than an orphaned Stalwart account (docs/rfc/mail-module.md §13)."""
    _, workspace = await _workspace(db_session)
    domain = await _domain(db_session, workspace)

    db_session.add(
        MailAccount(
            workspace_id=workspace.id,
            domain_id=domain.id,
            provider=MailProvider.STALWART,
            provider_account_id="pre-existing",
            email="ada@example.com",
        )
    )
    await db_session.flush()

    class FlakyDeleteMailClient(FakeMailClient):
        async def delete_account(self, account_id: str) -> None:
            self.delete_calls.append(account_id)
            raise MailClientError("mail server refused the delete")

    mail_client = FlakyDeleteMailClient()

    with pytest.raises(Exception) as exc_info:  # the DB's IntegrityError, not MailClientError
        await register_mail_account(
            db_session,
            workspace.id,
            MailAccountRegisterRequest(domain_id=domain.id, email="ada@example.com"),
            mail_client,
        )

    assert not isinstance(exc_info.value, MailClientError)
    assert mail_client.delete_calls == ["1"]


async def test_email_is_globally_unique(db_session: AsyncSession) -> None:
    _, workspace = await _workspace(db_session)
    domain = await _domain(db_session, workspace)
    db_session.add(
        MailAccount(
            workspace_id=workspace.id,
            domain_id=domain.id,
            provider=MailProvider.STALWART,
            provider_account_id="s-1",
            email="ada@example.com",
        )
    )
    await db_session.flush()

    db_session.add(
        MailAccount(
            workspace_id=workspace.id,
            domain_id=domain.id,
            provider=MailProvider.STALWART,
            provider_account_id="s-2",
            email="ada@example.com",
        )
    )
    with pytest.raises(Exception):  # unique index on lower(email)
        await db_session.flush()


async def test_provider_account_id_is_unique_per_provider(
    db_session: AsyncSession,
) -> None:
    _, workspace = await _workspace(db_session)
    domain = await _domain(db_session, workspace)
    db_session.add(
        MailAccount(
            workspace_id=workspace.id,
            domain_id=domain.id,
            provider=MailProvider.STALWART,
            provider_account_id="dup",
            email="a@example.com",
        )
    )
    await db_session.flush()

    db_session.add(
        MailAccount(
            workspace_id=workspace.id,
            domain_id=domain.id,
            provider=MailProvider.STALWART,
            provider_account_id="dup",
            email="b@example.com",
        )
    )
    with pytest.raises(Exception):  # unique (provider, provider_account_id)
        await db_session.flush()


async def test_get_and_list_accounts(db_session: AsyncSession) -> None:
    _, workspace = await _workspace(db_session)
    domain = await _domain(db_session, workspace)
    mail_client = FakeMailClient()

    account = await register_mail_account(
        db_session,
        workspace.id,
        MailAccountRegisterRequest(domain_id=domain.id, email="ada@example.com"),
        mail_client,
    )

    fetched = await get_mail_account(db_session, account.id)
    assert fetched is not None
    assert fetched.id == account.id

    listed = await list_mail_accounts(db_session, workspace.id)
    assert [a.email for a in listed] == ["ada@example.com"]


async def test_get_mail_domain_returns_none_when_missing(
    db_session: AsyncSession,
) -> None:
    assert await get_mail_domain(db_session, uuid.uuid4()) is None


async def test_account_domain_relationship(db_session: AsyncSession) -> None:
    _, workspace = await _workspace(db_session)
    domain = await _domain(db_session, workspace)
    mail_client = FakeMailClient()

    account = await register_mail_account(
        db_session,
        workspace.id,
        MailAccountRegisterRequest(domain_id=domain.id, email="ada@example.com"),
        mail_client,
    )

    # account → domain
    assert account.domain.id == domain.id

    # domain → accounts (reload the collection from the session)
    loaded = (
        await db_session.execute(select(MailDomain).where(MailDomain.id == domain.id))
    ).scalar_one()
    await db_session.refresh(loaded, ["accounts"])
    assert [a.id for a in loaded.accounts] == [account.id]


async def test_register_duplicate_email_raises_email_already_exists(
    db_session: AsyncSession,
) -> None:
    """A narrower check than the generic compensating-rollback tests above:
    the specific exception type callers (routers) branch on."""
    _, workspace = await _workspace(db_session)
    domain = await _domain(db_session, workspace)
    db_session.add(
        MailAccount(
            workspace_id=workspace.id,
            domain_id=domain.id,
            provider=MailProvider.STALWART,
            provider_account_id="pre-existing",
            email="ada@example.com",
        )
    )
    await db_session.flush()

    mail_client = FakeMailClient()

    with pytest.raises(EmailAlreadyExistsError):
        await register_mail_account(
            db_session,
            workspace.id,
            MailAccountRegisterRequest(domain_id=domain.id, email="ada@example.com"),
            mail_client,
        )
    assert mail_client.delete_calls == ["1"]


# --- update_mail_account / delete_mail_account -----------------------------


async def test_update_mail_account_display_name(db_session: AsyncSession) -> None:
    _, workspace = await _workspace(db_session)
    domain = await _domain(db_session, workspace)
    mail_client = FakeMailClient()
    account = await register_mail_account(
        db_session,
        workspace.id,
        MailAccountRegisterRequest(
            domain_id=domain.id, email="ada@example.com", display_name="Ada"
        ),
        mail_client,
    )

    updated = await update_mail_account(
        db_session, account, MailAccountUpdateRequest(display_name="Ada L.")
    )

    assert updated.display_name == "Ada L."
    # Ember-side only: no MailClient calls are made for a rename.
    assert mail_client.create_calls == [("ada@example.com", mail_client.create_calls[0][1])]
    assert mail_client.delete_calls == []


async def test_update_mail_account_status_suspends(db_session: AsyncSession) -> None:
    _, workspace = await _workspace(db_session)
    domain = await _domain(db_session, workspace)
    mail_client = FakeMailClient()
    account = await register_mail_account(
        db_session,
        workspace.id,
        MailAccountRegisterRequest(domain_id=domain.id, email="ada@example.com"),
        mail_client,
    )
    assert account.status == MailAccountStatus.ACTIVE


    updated = await update_mail_account(
        db_session, account, MailAccountUpdateRequest(status=MailAccountStatus.SUSPENDED)
    )

    assert updated.status == MailAccountStatus.SUSPENDED
    assert mail_client.delete_calls == []  # suspension never touches the mail server


async def test_update_mail_account_partial_leaves_other_field_untouched(
    db_session: AsyncSession,
) -> None:
    _, workspace = await _workspace(db_session)
    domain = await _domain(db_session, workspace)
    mail_client = FakeMailClient()
    account = await register_mail_account(
        db_session,
        workspace.id,
        MailAccountRegisterRequest(
            domain_id=domain.id, email="ada@example.com", display_name="Ada"
        ),
        mail_client,
    )

    updated = await update_mail_account(
        db_session, account, MailAccountUpdateRequest(status=MailAccountStatus.DISABLED)
    )

    assert updated.status == MailAccountStatus.DISABLED
    assert updated.display_name == "Ada"


async def test_delete_mail_account_calls_mail_client_then_removes_row(
    db_session: AsyncSession,
) -> None:
    _, workspace = await _workspace(db_session)
    domain = await _domain(db_session, workspace)
    mail_client = FakeMailClient()
    account = await register_mail_account(
        db_session,
        workspace.id,
        MailAccountRegisterRequest(domain_id=domain.id, email="ada@example.com"),
        mail_client,
    )
    account_id = account.id
    provider_account_id = account.provider_account_id

    await delete_mail_account(db_session, account, mail_client)

    assert mail_client.delete_calls == [provider_account_id]
    assert await get_mail_account(db_session, account_id) is None


async def test_delete_mail_account_mail_server_failure_keeps_row(
    db_session: AsyncSession,
) -> None:
    """If the mail server refuses the delete, nothing local is touched — the
    account row still exists, matching the create-side contract: the external
    call is asked first, and a failure there aborts before any DB change."""
    _, workspace = await _workspace(db_session)
    domain = await _domain(db_session, workspace)
    mail_client = FakeMailClient()
    account = await register_mail_account(
        db_session,
        workspace.id,
        MailAccountRegisterRequest(domain_id=domain.id, email="ada@example.com"),
        mail_client,
    )
    account_id = account.id

    failing_client = FakeMailClient(delete_error=MailClientError("mail server refused"))

    with pytest.raises(MailClientError):
        await delete_mail_account(db_session, account, failing_client)

    assert await get_mail_account(db_session, account_id) is not None
