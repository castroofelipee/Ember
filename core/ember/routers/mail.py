import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from ember.db import get_db
from ember.dependencies import get_current_user
from ember.mail import MailAccountAlreadyExistsError, MailClient, MailClientError, get_mail_client
from ember.models import MailAccount, MailDomain, User
from ember.schemas.mail import (
    MailAccountRegisterRequest,
    MailAccountResponse,
    MailAccountUpdateRequest,
    MailDomainCreateRequest,
    MailDomainResponse,
    MailDomainUpdateRequest,
)
from ember.services.mail import (
    DomainAlreadyExistsError,
    DomainHasAccountsError,
    EmailAlreadyExistsError,
    EmailDomainMismatchError,
    MailDomainNotFoundError,
    create_mail_domain,
    delete_mail_account,
    delete_mail_domain,
    get_mail_account,
    get_mail_domain,
    list_mail_accounts,
    list_mail_domains,
    register_mail_account,
    update_mail_account,
    update_mail_domain,
)
from ember.services.workspaces import NotAWorkspaceMemberError, assert_workspace_member

router = APIRouter(prefix="/api/workspaces", tags=["Mail"])

_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")
_ALREADY_EXISTS = HTTPException(
    status_code=status.HTTP_409_CONFLICT,
    detail="A domain with this name is already registered.",
)
_MAIL_UNAVAILABLE = HTTPException(
    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
    detail="Mail is not configured for this server.",
)


def _require_mail_client() -> MailClient:
    client = get_mail_client()
    if client is None:
        raise _MAIL_UNAVAILABLE
    return client


async def _require_membership(db: AsyncSession, workspace_id: uuid.UUID, user_id: uuid.UUID) -> None:
    try:
        await assert_workspace_member(db, workspace_id, user_id)
    except NotAWorkspaceMemberError as exc:
        raise _NOT_FOUND from exc


async def _get_domain_or_404(
    db: AsyncSession, workspace_id: uuid.UUID, domain_id: uuid.UUID
) -> MailDomain:
    domain = await get_mail_domain(db, domain_id)
    if domain is None or domain.workspace_id != workspace_id:
        raise _NOT_FOUND
    return domain


async def _get_account_or_404(
    db: AsyncSession, workspace_id: uuid.UUID, account_id: uuid.UUID
) -> MailAccount:
    account = await get_mail_account(db, account_id)
    if account is None or account.workspace_id != workspace_id:
        raise _NOT_FOUND
    return account


@router.post("/{workspace_id}/mail/domains", status_code=status.HTTP_201_CREATED)
async def create_mail_domain_route(
    workspace_id: uuid.UUID,
    data: MailDomainCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MailDomainResponse:
    await _require_membership(db, workspace_id, current_user.id)
    try:
        domain = await create_mail_domain(db, workspace_id, data)
    except DomainAlreadyExistsError as exc:
        raise _ALREADY_EXISTS from exc
    return MailDomainResponse.model_validate(domain)


@router.get("/{workspace_id}/mail/domains")
async def list_mail_domains_route(
    workspace_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[MailDomainResponse]:
    await _require_membership(db, workspace_id, current_user.id)
    domains = await list_mail_domains(db, workspace_id)
    return [MailDomainResponse.model_validate(d) for d in domains]


@router.get("/{workspace_id}/mail/domains/{domain_id}")
async def get_mail_domain_route(
    workspace_id: uuid.UUID,
    domain_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MailDomainResponse:
    await _require_membership(db, workspace_id, current_user.id)
    domain = await _get_domain_or_404(db, workspace_id, domain_id)
    return MailDomainResponse.model_validate(domain)


@router.patch("/{workspace_id}/mail/domains/{domain_id}")
async def update_mail_domain_route(
    workspace_id: uuid.UUID,
    domain_id: uuid.UUID,
    data: MailDomainUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MailDomainResponse:
    await _require_membership(db, workspace_id, current_user.id)
    domain = await _get_domain_or_404(db, workspace_id, domain_id)
    try:
        domain = await update_mail_domain(db, domain, data)
    except DomainAlreadyExistsError as exc:
        raise _ALREADY_EXISTS from exc
    return MailDomainResponse.model_validate(domain)


@router.delete("/{workspace_id}/mail/domains/{domain_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_mail_domain_route(
    workspace_id: uuid.UUID,
    domain_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    await _require_membership(db, workspace_id, current_user.id)
    domain = await _get_domain_or_404(db, workspace_id, domain_id)
    try:
        await delete_mail_domain(db, domain)
    except DomainHasAccountsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Domain still has mail accounts; remove them before deleting the domain.",
        ) from exc


@router.post("/{workspace_id}/mail/accounts", status_code=status.HTTP_201_CREATED)
async def create_mail_account_route(
    workspace_id: uuid.UUID,
    data: MailAccountRegisterRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    mail_client: MailClient = Depends(_require_mail_client),
) -> MailAccountResponse:
    await _require_membership(db, workspace_id, current_user.id)
    try:
        account = await register_mail_account(db, workspace_id, data, mail_client)
    except MailDomainNotFoundError as exc:
        raise _NOT_FOUND from exc
    except EmailDomainMismatchError as exc:
        raise HTTPException(
            status_code=422,
            detail="The address must belong to the selected domain.",
        ) from exc
    except (MailAccountAlreadyExistsError, EmailAlreadyExistsError) as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This address is already registered.",
        ) from exc
    except MailClientError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not reach the mail server. Please try again.",
        ) from exc
    return MailAccountResponse.model_validate(account)


@router.get("/{workspace_id}/mail/accounts")
async def list_mail_accounts_route(
    workspace_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[MailAccountResponse]:
    await _require_membership(db, workspace_id, current_user.id)
    accounts = await list_mail_accounts(db, workspace_id)
    return [MailAccountResponse.model_validate(a) for a in accounts]


@router.patch("/{workspace_id}/mail/accounts/{account_id}")
async def update_mail_account_route(
    workspace_id: uuid.UUID,
    account_id: uuid.UUID,
    data: MailAccountUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MailAccountResponse:
    await _require_membership(db, workspace_id, current_user.id)
    account = await _get_account_or_404(db, workspace_id, account_id)
    account = await update_mail_account(db, account, data)
    return MailAccountResponse.model_validate(account)


@router.delete("/{workspace_id}/mail/accounts/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_mail_account_route(
    workspace_id: uuid.UUID,
    account_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    mail_client: MailClient = Depends(_require_mail_client),
) -> None:
    await _require_membership(db, workspace_id, current_user.id)
    account = await _get_account_or_404(db, workspace_id, account_id)
    try:
        await delete_mail_account(db, account, mail_client)
    except MailClientError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not delete the account on the mail server. Please try again.",
        ) from exc
