import enum
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Enum, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ember.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from ember.models.mail_account import MailAccount


class MailDomainStatus(str, enum.Enum):
    """Lifecycle of a domain inside Ember. DNS verification is a later step
    (docs/rfc/mail-module.md §5) — this enum only tracks whether the workspace
    has enabled the domain, not whether MX/SPF/DKIM records are correct."""

    PENDING = "pending"
    ACTIVE = "active"
    DISABLED = "disabled"


class MailDomain(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A mail domain a workspace can send/receive on (e.g. ``example.com``).

    Ember only records ownership and lifecycle here. Actual mail routing, DKIM
    signing, and DNS are Stalwart's responsibility (docs/rfc/mail-module.md §3);
    Ember must not become a second copy of the mail server's configuration.
    """

    __tablename__ = "mail_domains"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    domain: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[MailDomainStatus] = mapped_column(
        Enum(MailDomainStatus, native_enum=False, length=16, validate_strings=True),
        nullable=False,
        default=MailDomainStatus.PENDING,
        server_default=MailDomainStatus.PENDING.value,
    )

    accounts: Mapped[list["MailAccount"]] = relationship(
        back_populates="domain", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_mail_domains_workspace_id", "workspace_id"),
        # A mail domain routes globally, so it can belong to only one workspace.
        # Stored case-insensitively, matching the users-email precedent in user.py.
        Index("ix_mail_domains_domain_lower", func.lower(domain), unique=True),
    )
