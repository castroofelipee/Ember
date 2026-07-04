import enum
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Enum, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ember.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from ember.models.mail_domain import MailDomain


class MailProvider(str, enum.Enum):
    """Which mail server backs the account. Only Stalwart today, but the column
    exists so provider ids stay unambiguous if a second backend is ever added
    (docs/rfc/mail-module.md §2 — the backend is meant to be swappable)."""

    STALWART = "stalwart"


class MailAccountStatus(str, enum.Enum):
    """Ember-side lifecycle of the mapping, not the mail server's own state."""

    ACTIVE = "active"
    SUSPENDED = "suspended"
    DISABLED = "disabled"


class MailAccount(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """An email account Ember knows about, mapping a Stalwart account into the
    workspace tenancy tree (the analogue of ``Calendar``).

    Ember stores only what it needs to integrate the account: which workspace
    and domain it belongs to, the owning user (personal) or none (shared), and
    the provider handle needed to manage it later. It never stores the password,
    mailboxes, or messages — those live in Stalwart (docs/rfc/mail-module.md §5).
    """

    __tablename__ = "mail_accounts"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    domain_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("mail_domains.id", ondelete="CASCADE"), nullable=False
    )
    # Personal account → the owning user; shared/company account (support@…) →
    # NULL. SET NULL (not CASCADE) so deleting a user doesn't silently drop a
    # shared address the workspace still relies on.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    provider: Mapped[MailProvider] = mapped_column(
        Enum(MailProvider, native_enum=False, length=32, validate_strings=True),
        nullable=False,
        default=MailProvider.STALWART,
        server_default=MailProvider.STALWART.value,
    )
    # The mail server's own account id (Stalwart principal id). Opaque handle
    # Ember uses to provision/rotate/delete the account later; kept as a string
    # to stay provider-agnostic.
    provider_account_id: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    # Maps to Stalwart's principal ``description`` (the human-readable name).
    display_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[MailAccountStatus] = mapped_column(
        Enum(MailAccountStatus, native_enum=False, length=16, validate_strings=True),
        nullable=False,
        default=MailAccountStatus.ACTIVE,
        server_default=MailAccountStatus.ACTIVE.value,
    )

    domain: Mapped["MailDomain"] = relationship(back_populates="accounts")

    __table_args__ = (
        Index("ix_mail_accounts_workspace_id", "workspace_id"),
        Index("ix_mail_accounts_domain_id", "domain_id"),
        Index("ix_mail_accounts_user_id", "user_id"),
        # One Ember row per address; addresses are unique, case-insensitive.
        Index("ix_mail_accounts_email_lower", func.lower(email), unique=True),
        # Never register the same provider account twice.
        UniqueConstraint(
            "provider",
            "provider_account_id",
            name="uq_mail_accounts_provider_provider_account_id",
        ),
    )
