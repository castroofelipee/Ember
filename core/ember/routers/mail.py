import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from ember.db import get_db
from ember.dependencies import get_current_user
from ember.mail import (
    MailAccountAlreadyExistsError,
    MailAuthenticationError,
    MailClient,
    MailClientError,
    MailSender,
    MailConnectionError,
    MailDomainNotProvisionedError,
    MailTimeoutError,
    get_mail_client,
    get_mail_sender,
)
from ember.models import MailAccount, MailDomain, User
from ember.schemas.mail import (
    MailAddressResponse,
    MailboxResponse,
    MailFolder,
    MailAccountRegisterRequest,
    MailAccountResponse,
    MailAccountUpdateRequest,
    MailDomainCreateRequest,
    MailDomainResponse,
    MailDomainUpdateRequest,
    MailMarkReadResponse,
    MailMessageDetailResponse,
    MailMessagePageResponse,
    MailMessageSendRequest,
    MailMessageSendResponse,
    MailMessageSummaryResponse,
    MailMessageUpdateRequest,
    MailThreadPageResponse,
    MailThreadPreviewResponse,
    MailThreadResponse,
)
from ember.services.mail import (
    DomainAlreadyExistsError,
    DomainHasAccountsError,
    EmailAlreadyExistsError,
    EmailDomainMismatchError,
    MailAccountNotActiveError,
    MailDomainNotFoundError,
    create_mail_domain,
    delete_mail_account,
    delete_mail_domain,
    get_mail_account,
    get_mail_domain,
    get_workspace_message,
    get_workspace_thread,
    list_mail_accounts,
    list_mail_domains,
    list_workspace_mailboxes,
    list_workspace_messages,
    list_workspace_thread_previews,
    mark_workspace_folder_read,
    register_mail_account,
    send_mail_message,
    update_workspace_message,
    update_mail_account,
    update_mail_domain,
)
from ember.services.workspaces import NotAWorkspaceMemberError, assert_workspace_member

logger = logging.getLogger(__name__)

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


def _require_mail_sender(
    mail_client: MailClient = Depends(_require_mail_client),
) -> MailSender:
    sender = get_mail_sender(mail_client)
    if sender is None:
        raise _MAIL_UNAVAILABLE
    return sender


async def _require_membership(
    db: AsyncSession, workspace_id: uuid.UUID, user_id: uuid.UUID
) -> None:
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


def _mail_address_response(address) -> MailAddressResponse | None:
    if address is None:
        return None
    return MailAddressResponse(email=address.email, name=address.name)


def _message_summary_response(item) -> MailMessageSummaryResponse:
    return MailMessageSummaryResponse(
        account_id=item.account_id,
        account_email=item.account_email,
        id=item.message.id,
        thread_id=item.message.thread_id,
        mailbox_ids=list(item.message.mailbox_ids),
        keywords=list(item.message.keywords),
        has_attachment=item.message.has_attachment,
        sender=_mail_address_response(item.message.sender),
        subject=item.message.subject,
        preview=item.message.preview,
        received_at=item.message.received_at,
        size=item.message.size,
    )


def _message_detail_response(item) -> MailMessageDetailResponse:
    summary = _message_summary_response(item)
    return MailMessageDetailResponse(
        **summary.model_dump(),
        to=[
            MailAddressResponse(email=address.email, name=address.name)
            for address in item.message.to
        ],
        cc=[
            MailAddressResponse(email=address.email, name=address.name)
            for address in item.message.cc
        ],
        bcc=[
            MailAddressResponse(email=address.email, name=address.name)
            for address in item.message.bcc
        ],
        reply_to=[
            MailAddressResponse(email=address.email, name=address.name)
            for address in item.message.reply_to
        ],
        text_body=item.message.text_body,
        html_body=item.message.html_body,
    )


def _thread_response(items) -> MailThreadResponse:
    first = items[0]
    return MailThreadResponse(
        account_id=first.account_id,
        account_email=first.account_email,
        thread_id=first.message.thread_id,
        messages=[_message_detail_response(item) for item in items],
    )


def _thread_preview_response(item) -> MailThreadPreviewResponse:
    latest = max(item.messages, key=lambda message: message.received_at)
    participants_by_email = {}
    for message in item.messages:
        for address in (message.sender, *message.to, *message.cc):
            if address is None:
                continue
            participants_by_email.setdefault(
                address.email.lower(),
                MailAddressResponse(email=address.email, name=address.name),
            )

    latest_message = MailMessageSummaryResponse(
        account_id=item.account_id,
        account_email=item.account_email,
        id=latest.id,
        thread_id=latest.thread_id,
        mailbox_ids=list(latest.mailbox_ids),
        keywords=list(latest.keywords),
        has_attachment=latest.has_attachment,
        sender=_mail_address_response(latest.sender),
        subject=latest.subject,
        preview=latest.preview,
        received_at=latest.received_at,
        size=latest.size,
    )
    return MailThreadPreviewResponse(
        account_id=item.account_id,
        account_email=item.account_email,
        thread_id=item.thread_id,
        subject=latest.subject,
        preview=latest.preview,
        participants=list(participants_by_email.values()),
        latest_message=latest_message,
        message_count=len(item.messages),
        unread_count=sum(1 for message in item.messages if "$seen" not in message.keywords),
        has_attachment=any(message.has_attachment for message in item.messages),
        received_at=latest.received_at,
    )


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
    except MailDomainNotProvisionedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This domain has not been set up on the mail server yet.",
        ) from exc
    except MailAuthenticationError as exc:
        logger.warning("Mail server rejected admin credentials creating %s: %s", data.email, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Mail server rejected the configured admin credentials.",
        ) from exc
    except (MailConnectionError, MailTimeoutError) as exc:
        # Logged because the detail below is deliberately generic for the
        # caller — transport failures are operational noise for the UI.
        logger.warning("Mail server error creating account %s: %s", data.email, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not reach the mail server. Please try again.",
        ) from exc
    except MailClientError as exc:
        logger.warning("Mail server rejected account create for %s: %s", data.email, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Mail server rejected the account creation request.",
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


@router.get("/{workspace_id}/mail/mailboxes")
async def list_mailboxes_route(
    workspace_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    mail_client: MailClient = Depends(_require_mail_client),
) -> list[MailboxResponse]:
    await _require_membership(db, workspace_id, current_user.id)
    try:
        mailboxes = await list_workspace_mailboxes(db, workspace_id, mail_client)
    except MailAuthenticationError as exc:
        logger.warning("Mail server rejected admin credentials listing mailboxes: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Mail server rejected the configured admin credentials.",
        ) from exc
    except (MailConnectionError, MailTimeoutError) as exc:
        logger.warning("Mail server error listing mailboxes: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not reach the mail server. Please try again.",
        ) from exc
    except MailClientError as exc:
        logger.warning("Mail server rejected mailbox list: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Mail server rejected the mailbox list request.",
        ) from exc
    return [
        MailboxResponse(
            account_id=item.account_id,
            account_email=item.account_email,
            mailbox_id=item.mailbox.id,
            name=item.mailbox.name,
            role=item.mailbox.role,
            total_emails=item.mailbox.total_emails,
            total_threads=item.mailbox.total_threads,
            unread_emails=item.mailbox.unread_emails,
            unread_threads=item.mailbox.unread_threads,
        )
        for item in mailboxes
    ]


@router.get("/{workspace_id}/mail/messages")
async def list_mail_messages_route(
    workspace_id: uuid.UUID,
    folder: MailFolder = "inbox",
    limit: int = 50,
    offset: int = 0,
    account_id: uuid.UUID | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    mail_client: MailClient = Depends(_require_mail_client),
) -> MailMessagePageResponse:
    await _require_membership(db, workspace_id, current_user.id)
    account = (
        None if account_id is None else await _get_account_or_404(db, workspace_id, account_id)
    )
    try:
        messages, has_more = await list_workspace_messages(
            db,
            workspace_id,
            mail_client,
            folder=folder,
            limit=max(1, min(limit, 100)),
            offset=max(0, offset),
            account=account,
        )
    except MailAuthenticationError as exc:
        logger.warning("Mail server rejected admin credentials listing messages: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Mail server rejected the configured admin credentials.",
        ) from exc
    except (MailConnectionError, MailTimeoutError) as exc:
        logger.warning("Mail server error listing messages: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not reach the mail server. Please try again.",
        ) from exc
    except MailClientError as exc:
        logger.warning("Mail server rejected message list: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Mail server rejected the message list request.",
        ) from exc
    return MailMessagePageResponse(
        items=[_message_summary_response(item) for item in messages], has_more=has_more
    )


@router.get("/{workspace_id}/mail/threads")
async def list_mail_threads_route(
    workspace_id: uuid.UUID,
    folder: MailFolder = "inbox",
    limit: int = 50,
    offset: int = 0,
    account_id: uuid.UUID | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    mail_client: MailClient = Depends(_require_mail_client),
) -> MailThreadPageResponse:
    await _require_membership(db, workspace_id, current_user.id)
    account = (
        None if account_id is None else await _get_account_or_404(db, workspace_id, account_id)
    )
    try:
        previews, has_more = await list_workspace_thread_previews(
            db,
            workspace_id,
            mail_client,
            folder=folder,
            limit=max(1, min(limit, 100)),
            offset=max(0, offset),
            account=account,
        )
    except MailAuthenticationError as exc:
        logger.warning("Mail server rejected admin credentials listing threads: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Mail server rejected the configured admin credentials.",
        ) from exc
    except (MailConnectionError, MailTimeoutError) as exc:
        logger.warning("Mail server error listing threads: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not reach the mail server. Please try again.",
        ) from exc
    except MailClientError as exc:
        logger.warning("Mail server rejected thread list: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Mail server rejected the thread list request.",
        ) from exc
    return MailThreadPageResponse(
        items=[_thread_preview_response(item) for item in previews], has_more=has_more
    )


@router.post("/{workspace_id}/mail/read")
async def mark_mail_folder_read_route(
    workspace_id: uuid.UUID,
    folder: MailFolder = "inbox",
    account_id: uuid.UUID | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    mail_client: MailClient = Depends(_require_mail_client),
) -> MailMarkReadResponse:
    await _require_membership(db, workspace_id, current_user.id)
    account = (
        None if account_id is None else await _get_account_or_404(db, workspace_id, account_id)
    )
    try:
        marked = await mark_workspace_folder_read(
            db, workspace_id, mail_client, folder=folder, account=account
        )
    except MailAuthenticationError as exc:
        logger.warning("Mail server rejected admin credentials marking folder read: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Mail server rejected the configured admin credentials.",
        ) from exc
    except (MailConnectionError, MailTimeoutError) as exc:
        logger.warning("Mail server error marking folder read: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not reach the mail server. Please try again.",
        ) from exc
    except MailClientError as exc:
        logger.warning("Mail server rejected mark-folder-read: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Mail server rejected the mark-as-read request.",
        ) from exc
    return MailMarkReadResponse(marked=marked)


@router.get("/{workspace_id}/mail/accounts/{account_id}/messages/{message_id}")
async def get_mail_message_route(
    workspace_id: uuid.UUID,
    account_id: uuid.UUID,
    message_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    mail_client: MailClient = Depends(_require_mail_client),
) -> MailMessageDetailResponse:
    await _require_membership(db, workspace_id, current_user.id)
    account = await _get_account_or_404(db, workspace_id, account_id)
    try:
        message = await get_workspace_message(account, message_id, mail_client)
    except MailAuthenticationError as exc:
        logger.warning(
            "Mail server rejected admin credentials loading message %s: %s", message_id, exc
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Mail server rejected the configured admin credentials.",
        ) from exc
    except (MailConnectionError, MailTimeoutError) as exc:
        logger.warning("Mail server error loading message %s: %s", message_id, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not reach the mail server. Please try again.",
        ) from exc
    except MailClientError as exc:
        logger.warning("Mail server rejected message get %s: %s", message_id, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Mail server rejected the message fetch request.",
        ) from exc
    return _message_detail_response(message)


@router.patch("/{workspace_id}/mail/accounts/{account_id}/messages/{message_id}")
async def update_mail_message_route(
    workspace_id: uuid.UUID,
    account_id: uuid.UUID,
    message_id: str,
    data: MailMessageUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    mail_client: MailClient = Depends(_require_mail_client),
) -> MailMessageDetailResponse:
    await _require_membership(db, workspace_id, current_user.id)
    account = await _get_account_or_404(db, workspace_id, account_id)
    try:
        message = await update_workspace_message(account, message_id, data, mail_client)
    except MailAuthenticationError as exc:
        logger.warning(
            "Mail server rejected admin credentials updating message %s: %s", message_id, exc
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Mail server rejected the configured admin credentials.",
        ) from exc
    except (MailConnectionError, MailTimeoutError) as exc:
        logger.warning("Mail server error updating message %s: %s", message_id, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not reach the mail server. Please try again.",
        ) from exc
    except MailClientError as exc:
        logger.warning("Mail server rejected message update %s: %s", message_id, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Mail server rejected the message update request.",
        ) from exc
    return _message_detail_response(message)


@router.get("/{workspace_id}/mail/accounts/{account_id}/threads/{thread_id}")
async def get_mail_thread_route(
    workspace_id: uuid.UUID,
    account_id: uuid.UUID,
    thread_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    mail_client: MailClient = Depends(_require_mail_client),
) -> MailThreadResponse:
    await _require_membership(db, workspace_id, current_user.id)
    account = await _get_account_or_404(db, workspace_id, account_id)
    try:
        thread = await get_workspace_thread(account, thread_id, mail_client)
    except MailAuthenticationError as exc:
        logger.warning(
            "Mail server rejected admin credentials loading thread %s: %s", thread_id, exc
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Mail server rejected the configured admin credentials.",
        ) from exc
    except (MailConnectionError, MailTimeoutError) as exc:
        logger.warning("Mail server error loading thread %s: %s", thread_id, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not reach the mail server. Please try again.",
        ) from exc
    except MailClientError as exc:
        logger.warning("Mail server rejected thread get %s: %s", thread_id, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Mail server rejected the thread fetch request.",
        ) from exc
    return _thread_response(thread)


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
    except MailAuthenticationError as exc:
        logger.warning(
            "Mail server rejected admin credentials deleting %s: %s",
            account.provider_account_id,
            exc,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Mail server rejected the configured admin credentials.",
        ) from exc
    except (MailConnectionError, MailTimeoutError) as exc:
        logger.warning(
            "Mail server error deleting account %s: %s", account.provider_account_id, exc
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not delete the account on the mail server. Please try again.",
        ) from exc
    except MailClientError as exc:
        logger.warning(
            "Mail server rejected account delete for %s: %s", account.provider_account_id, exc
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Mail server rejected the account deletion request.",
        ) from exc


@router.post("/{workspace_id}/mail/accounts/{account_id}/messages/send")
async def send_mail_message_route(
    workspace_id: uuid.UUID,
    account_id: uuid.UUID,
    data: MailMessageSendRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    mail_sender: MailSender = Depends(_require_mail_sender),
) -> MailMessageSendResponse:
    await _require_membership(db, workspace_id, current_user.id)
    account = await _get_account_or_404(db, workspace_id, account_id)
    try:
        result = await send_mail_message(account, data, mail_sender)
    except MailAccountNotActiveError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This mail account is not active.",
        ) from exc
    except MailAuthenticationError as exc:
        logger.warning(
            "Outbound mail provider rejected authorization sending from %s: %s",
            account.email,
            exc,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Outbound mail provider rejected the configured credentials or sender domain.",
        ) from exc
    except (MailConnectionError, MailTimeoutError) as exc:
        logger.warning("Outbound mail provider error sending from %s: %s", account.email, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not reach the outbound mail provider. Please try again.",
        ) from exc
    except MailClientError as exc:
        logger.warning("Outbound mail provider rejected send from %s: %s", account.email, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Outbound mail provider rejected the send request.",
        ) from exc
    return MailMessageSendResponse(
        email_id=result.email_id,
        submission_id=result.submission_id,
    )
