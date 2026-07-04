import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from ember.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Invite(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Single-use signup gate: registration is closed to the internet by default,
    so /api/auth/signup requires a valid, unused, unexpired invite code.

    Only the hash is ever stored, same as `RefreshToken`. No relationships are
    declared here (nothing in this codebase needs to traverse Invite from
    User or vice versa yet) — just the two FK columns for audit purposes.
    """

    __tablename__ = "invites"

    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE")
    )
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    used_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        Index("ix_invites_created_by_user_id", "created_by_user_id"),
        Index("ix_invites_code_hash", "code_hash", unique=True),
    )
