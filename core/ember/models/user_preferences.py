import uuid
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ember.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from ember.models.user import User


class UserPreferences(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "user_preferences"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    timezone: Mapped[str] = mapped_column(
        String(64), nullable=False, default="UTC", server_default="UTC"
    )
    locale: Mapped[str] = mapped_column(
        String(10), nullable=False, default="en-US", server_default="en-US"
    )
    # 0 = Sunday .. 6 = Saturday (ISO-agnostic; UI decides how to render it).
    week_starts_on: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=0, server_default="0"
    )

    user: Mapped["User"] = relationship(back_populates="preferences")

    __table_args__ = (
        CheckConstraint(
            "week_starts_on >= 0 AND week_starts_on <= 6",
            name="week_starts_on_range",
        ),
    )
