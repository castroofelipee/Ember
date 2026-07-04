import contextlib
import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ember.mail import MailClient, MailClientError
from ember.models import MailAccount, MailDomain
from ember.schemas.mail import (
    MailAccountRegisterRequest,
    MailAccountUpdateRequest,
    MailDomainCreateRequest,
    MailDomainUpdateRequest,
    email_domain,
)
from ember.security import generate_mail_account_password


class MailDomainNotFoundError(Exception):
    """The referenced domain does not exist in the workspace. Surfaced as 404,
    like every other missing resource (routers/workspaces.py invariant)."""


class DomainAlreadyExistsError(Exception):
    """Raised when the unique(lower(domain)) constraint on `mail_domains`
    rejects a create or rename (mirrors `EmailAlreadyRegisteredError` in
    services/auth.py)."""


class DomainHasAccountsError(Exception):
    """Raised when deleting a domain that still has mail accounts on it. Ember
    does not cascade-delete Stalwart accounts here (that would silently orphan
    real mailboxes — the same consistency concern `register_mail_account`
    guards against), so the caller must remove the accounts first."""


class EmailDomainMismatchError(Exception):
    """The account's address is not on the domain it is being registered under.
    Ember must not create an address that its own domain record can't route."""


class EmailAlreadyExistsError(Exception):
    """Raised when the unique(lower(email)) constraint on `mail_accounts`
    rejects a registration — Ember already has a row for this address even
    though the mail server accepted the create call (mirrors
    `DomainAlreadyExistsError` / `EmailAlreadyRegisteredError` in services/auth.py)."""


async def create_mail_domain(
    session: AsyncSession, workspace_id: uuid.UUID, data: MailDomainCreateRequest
) -> MailDomain:
    domain = MailDomain(workspace_id=workspace_id, domain=data.domain)
    session.add(domain)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise DomainAlreadyExistsError(data.domain) from exc
    return domain


async def get_mail_domain(
    session: AsyncSession, domain_id: uuid.UUID
) -> MailDomain | None:
    return await session.get(MailDomain, domain_id)


async def list_mail_domains(
    session: AsyncSession, workspace_id: uuid.UUID
) -> list[MailDomain]:
    return list(
        (
            await session.execute(
                select(MailDomain)
                .where(MailDomain.workspace_id == workspace_id)
                .order_by(MailDomain.created_at)
            )
        )
        .scalars()
        .all()
    )


async def update_mail_domain(
    session: AsyncSession, domain: MailDomain, data: MailDomainUpdateRequest
) -> MailDomain:
    if data.domain is not None:
        domain.domain = data.domain
    if data.status is not None:
        domain.status = data.status

    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise DomainAlreadyExistsError(data.domain) from exc
    await session.refresh(domain)
    return domain


async def delete_mail_domain(session: AsyncSession, domain: MailDomain) -> None:
    has_accounts = (
        await session.execute(
            select(MailAccount.id).where(MailAccount.domain_id == domain.id).limit(1)
        )
    ).scalar_one_or_none() is not None
    if has_accounts:
        raise DomainHasAccountsError()

    await session.delete(domain)
    await session.flush()


async def register_mail_account(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    data: MailAccountRegisterRequest,
    mail_client: MailClient,
) -> MailAccount:
    """Provision a mail account on the mail server and record it in Ember.

    Order matters for consistency between the two systems (docs/rfc/mail-module.md
    §5, §13 "sync correctness"): the workspace/domain are validated first (no
    side effect on failure), then the mail server is asked to create the account
    *before* anything is written to Ember's database — if that call fails,
    nothing here is persisted. Only once the mail server confirms creation do we
    add the local row; if *that* fails (e.g. a uniqueness race), we compensate
    by deleting the account we just created on the mail server, so a failed
    registration never leaves an orphaned Stalwart account with no Ember row
    behind it.
    """
    domain = await session.get(MailDomain, data.domain_id)
    if domain is None or domain.workspace_id != workspace_id:
        raise MailDomainNotFoundError()
    if email_domain(data.email) != domain.domain:
        raise EmailDomainMismatchError()

    # Ember never stores mail-server passwords (docs/rfc/mail-module.md §5): a
    # throwaway credential is generated, handed to the mail server, and
    # discarded — it is never persisted or returned.
    password = generate_mail_account_password()
    provisioned = await mail_client.create_account(data.email, password)

    account = MailAccount(
        workspace_id=workspace_id,
        domain_id=domain.id,
        user_id=data.user_id,
        provider_account_id=provisioned.id,
        email=data.email,
        display_name=data.display_name,
    )
    session.add(account)
    try:
        await session.flush()
    except IntegrityError as exc:
        with contextlib.suppress(MailClientError):
            await mail_client.delete_account(provisioned.id)
        await session.rollback()
        raise EmailAlreadyExistsError(data.email) from exc
    except Exception:
        # Best-effort compensation: an orphaned Stalwart account is a lesser
        # problem than swallowing the error that caused this branch, so a
        # failure here does not shadow the original exception.
        with contextlib.suppress(MailClientError):
            await mail_client.delete_account(provisioned.id)
        raise
    return account


async def get_mail_account(
    session: AsyncSession, account_id: uuid.UUID
) -> MailAccount | None:
    return await session.get(MailAccount, account_id)


async def list_mail_accounts(
    session: AsyncSession, workspace_id: uuid.UUID
) -> list[MailAccount]:
    return list(
        (
            await session.execute(
                select(MailAccount)
                .where(MailAccount.workspace_id == workspace_id)
                .order_by(MailAccount.created_at)
            )
        )
        .scalars()
        .all()
    )


async def update_mail_account(
    session: AsyncSession, account: MailAccount, data: MailAccountUpdateRequest
) -> MailAccount:
    """Ember-side bookkeeping only: neither field is mirrored to the mail
    server (docs/rfc/mail-module.md §5) — there is no `MailClient` operation
    for renaming or suspending an account yet."""
    if data.display_name is not None:
        account.display_name = data.display_name
    if data.status is not None:
        account.status = data.status

    await session.flush()
    await session.refresh(account)
    return account


async def delete_mail_account(
    session: AsyncSession, account: MailAccount, mail_client: MailClient
) -> None:
    """Delete the account from the mail server, then remove Ember's row.

    Mirrors `register_mail_account`'s external-call-first ordering: if the
    mail server delete fails, nothing here is touched. Once it succeeds, the
    local row is removed — but unlike registration there is no reverse
    operation to compensate with if *that* step then fails (the mail server
    side is already gone and cannot be un-deleted), so a failure here would
    leave a stale Ember row pointing at a nonexistent account. This is a
    single-row delete keyed on a primary key rather than a step that can hit a
    unique constraint, so the risk is low; a retry-safe repair pass belongs to
    docs/rfc/mail-module.md §13's rebuildability story, not this call.
    """
    await mail_client.delete_account(account.provider_account_id)
    await session.delete(account)
    await session.flush()
