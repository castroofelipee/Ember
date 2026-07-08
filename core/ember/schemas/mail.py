import re
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from ember.models.mail_account import MailAccountStatus, MailProvider
from ember.models.mail_domain import MailDomainStatus

# Deliberately permissive: full RFC 5322 validation belongs to the mail server,
# not to Ember. This only rejects obviously malformed input (no "@", spaces,
# empty local/domain part) before it reaches the database.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_DOMAIN_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")


def email_domain(email: str) -> str:
    """The domain part of an address, lowercased. Assumes a validated address."""
    return email.rsplit("@", 1)[1]


def _normalize_domain(value: str) -> str:
    normalized = value.strip().lower()
    if not _DOMAIN_RE.match(normalized):
        raise ValueError("domain must be a valid hostname like example.com")
    return normalized


class MailDomainCreateRequest(BaseModel):
    domain: str = Field(min_length=3, max_length=255)

    @field_validator("domain")
    @classmethod
    def normalize_domain(cls, value: str) -> str:
        return _normalize_domain(value)


class MailDomainUpdateRequest(BaseModel):
    """Partial update: only supplied fields change (mirrors
    `schemas.users.PreferencesUpdateRequest`). DNS verification does not exist
    yet (docs/rfc/mail-module.md — deferred), so `status` is a manual admin
    override for now rather than something a background job sets."""

    domain: str | None = Field(default=None, min_length=3, max_length=255)
    status: MailDomainStatus | None = None

    @field_validator("domain")
    @classmethod
    def normalize_domain(cls, value: str | None) -> str | None:
        return None if value is None else _normalize_domain(value)


class MailDomainResponse(BaseModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    domain: str
    status: MailDomainStatus
    created_at: datetime

    model_config = {"from_attributes": True}


class MailAccountRegisterRequest(BaseModel):
    """Request to provision a new mail account. The service calls the mail
    server itself and records the handle it returns (docs/rfc/mail-module.md
    §5) — callers never supply a provider id or a password."""

    domain_id: uuid.UUID
    email: str = Field(max_length=320)
    user_id: uuid.UUID | None = None
    display_name: str | None = Field(default=None, max_length=120)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not _EMAIL_RE.match(normalized):
            raise ValueError("email must be a valid address like user@example.com")
        return normalized

    @field_validator("display_name")
    @classmethod
    def normalize_display_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class MailAccountUpdateRequest(BaseModel):
    """Partial update: only supplied fields change (mirrors
    `MailDomainUpdateRequest`). Password rotation isn't part of this request —
    `MailClient.set_password` is still an unimplemented stub. `status` is
    Ember-side bookkeeping only (e.g. suspending an account); there is no mail
    server operation for it, matching how `MailDomain.status` stays local
    until DNS verification exists."""

    display_name: str | None = Field(default=None, max_length=120)
    status: MailAccountStatus | None = None

    @field_validator("display_name")
    @classmethod
    def normalize_display_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class MailAccountResponse(BaseModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    domain_id: uuid.UUID
    user_id: uuid.UUID | None
    provider: MailProvider
    provider_account_id: str
    email: str
    display_name: str | None
    status: MailAccountStatus
    created_at: datetime

    model_config = {"from_attributes": True}


def _normalize_email_address(value: str) -> str:
    normalized = value.strip().lower()
    if not _EMAIL_RE.match(normalized):
        raise ValueError("email must be a valid address like user@example.com")
    return normalized


def _normalize_email_list(values: list[str]) -> list[str]:
    normalized = [_normalize_email_address(value) for value in values]
    if len(set(normalized)) != len(normalized):
        raise ValueError("email recipients must be unique")
    return normalized


class MailMessageSendRequest(BaseModel):
    to: list[str] = Field(min_length=1, max_length=100)
    cc: list[str] = Field(default_factory=list, max_length=100)
    bcc: list[str] = Field(default_factory=list, max_length=100)
    subject: str = Field(default="", max_length=998)
    text: str = Field(min_length=1, max_length=1_000_000)

    @field_validator("to", "cc", "bcc")
    @classmethod
    def normalize_recipients(cls, value: list[str]) -> list[str]:
        return _normalize_email_list(value)

    @field_validator("subject")
    @classmethod
    def normalize_subject(cls, value: str) -> str:
        return value.strip()


class MailMessageSendResponse(BaseModel):
    email_id: str
    submission_id: str


MailFolder = Literal["inbox", "sent", "drafts", "archive", "trash", "junk"]


class MailAddressResponse(BaseModel):
    email: str
    name: str | None = None


class MailboxResponse(BaseModel):
    account_id: uuid.UUID
    account_email: str
    mailbox_id: str
    name: str
    role: str | None
    total_emails: int
    total_threads: int
    unread_emails: int
    unread_threads: int


class MailMessageSummaryResponse(BaseModel):
    account_id: uuid.UUID
    account_email: str
    id: str
    thread_id: str
    mailbox_ids: list[str]
    keywords: list[str]
    has_attachment: bool
    sender: MailAddressResponse | None
    subject: str
    preview: str
    received_at: datetime
    size: int


class MailMessageDetailResponse(MailMessageSummaryResponse):
    to: list[MailAddressResponse]
    cc: list[MailAddressResponse]
    bcc: list[MailAddressResponse]
    reply_to: list[MailAddressResponse]
    text_body: str
    html_body: str


class MailMessageUpdateRequest(BaseModel):
    seen: bool | None = None
    flagged: bool | None = None
    folder: MailFolder | None = None


class MailThreadResponse(BaseModel):
    account_id: uuid.UUID
    account_email: str
    thread_id: str
    messages: list[MailMessageDetailResponse]


class MailThreadPreviewResponse(BaseModel):
    account_id: uuid.UUID
    account_email: str
    thread_id: str
    subject: str
    preview: str
    participants: list[MailAddressResponse]
    latest_message: MailMessageSummaryResponse
    message_count: int
    unread_count: int
    has_attachment: bool
    received_at: datetime


class MailMessagePageResponse(BaseModel):
    """One page of a folder listing (docs pattern: Gmail-style "page 2", not
    infinite scroll). `has_more` tells the client whether another page exists
    without requiring an expensive total count from the mail server."""

    items: list[MailMessageSummaryResponse]
    has_more: bool


class MailThreadPageResponse(BaseModel):
    items: list[MailThreadPreviewResponse]
    has_more: bool


class MailMarkReadResponse(BaseModel):
    """Result of a bulk "mark all as read" over a folder. `marked` is the
    number of messages whose unread flag was cleared."""

    marked: int


__all__ = [
    "MailAddressResponse",
    "MailboxResponse",
    "MailFolder",
    "MailAccountRegisterRequest",
    "MailAccountResponse",
    "MailAccountUpdateRequest",
    "MailDomainCreateRequest",
    "MailDomainResponse",
    "MailDomainUpdateRequest",
    "MailMarkReadResponse",
    "MailMessageDetailResponse",
    "MailMessagePageResponse",
    "MailMessageSendRequest",
    "MailMessageSendResponse",
    "MailMessageSummaryResponse",
    "MailMessageUpdateRequest",
    "MailThreadPageResponse",
    "MailThreadPreviewResponse",
    "MailThreadResponse",
    "email_domain",
]
