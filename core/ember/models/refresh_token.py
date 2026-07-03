import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ember.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from ember.models.session import Session


class RefreshToken(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Rotating refresh-token material tied to a `Session` (docs/authentication.md §2/§4.2).

    Only the hash is ever stored. `replaces_id` chains rotations so reuse of an
    already-`used_at` token can be detected (theft signal -> revoke the session).
    """

    __tablename__ = "refresh_tokens"

    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"))
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    replaces_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("refresh_tokens.id", ondelete="SET NULL"), nullable=True
    )

    session: Mapped["Session"] = relationship(back_populates="refresh_tokens")

    __table_args__ = (
        Index("ix_refresh_tokens_session_id", "session_id"),
        Index("ix_refresh_tokens_token_hash", "token_hash", unique=True),
    )
