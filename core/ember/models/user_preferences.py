import uuid
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, Index, SmallInteger, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ember.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from ember.models.user import User


class UserPreferences(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One row per (user, workspace): each workspace gets its own schedule and
    display settings rather than one global configuration following the user
    everywhere."""

    __tablename__ = "user_preferences"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
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
    # Working hours as whole-hour bounds [start, end); drives which rows the
    # calendar shades as work time. start in 0..23, end in 1..24, start < end.
    work_day_start: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=9, server_default="9"
    )
    work_day_end: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=17, server_default="17"
    )
    # How hour/event times render: "12h" (AM/PM) or "24h".
    time_format: Mapped[str] = mapped_column(
        String(3), nullable=False, default="12h", server_default="12h"
    )

    user: Mapped["User"] = relationship(back_populates="preferences")

    __table_args__ = (
        UniqueConstraint("user_id", "workspace_id", name="uq_user_preferences_user_id_workspace_id"),
        Index("ix_user_preferences_workspace_id", "workspace_id"),
        CheckConstraint(
            "week_starts_on >= 0 AND week_starts_on <= 6",
            name="week_starts_on_range",
        ),
        CheckConstraint(
            "work_day_start >= 0 AND work_day_start <= 23",
            name="work_day_start_range",
        ),
        CheckConstraint(
            "work_day_end >= 1 AND work_day_end <= 24",
            name="work_day_end_range",
        ),
        CheckConstraint(
            "work_day_start < work_day_end",
            name="work_day_start_before_end",
        ),
    )
