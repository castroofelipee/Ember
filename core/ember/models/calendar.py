import uuid

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from ember.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

DEFAULT_CALENDAR_COLOR = "#4f46e5"


class Calendar(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "calendars"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    color: Mapped[str] = mapped_column(
        String(7), nullable=False, default=DEFAULT_CALENDAR_COLOR, server_default=DEFAULT_CALENDAR_COLOR
    )

    __table_args__ = (Index("ix_calendars_workspace_id", "workspace_id"),)
