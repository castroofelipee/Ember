import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ember.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Event(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "events"

    calendar_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("calendars.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    location: Mapped[str | None] = mapped_column(String(300), nullable=True)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    all_day: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    # Optional per-event override; when null the calendar's color is used.
    color: Mapped[str | None] = mapped_column(String(7), nullable=True)

    attendees: Mapped[list["EventAttendee"]] = relationship(
        back_populates="event",
        cascade="all, delete-orphan",
        order_by="EventAttendee.email",
    )

    __table_args__ = (
        Index("ix_events_calendar_id", "calendar_id"),
        # Range queries filter on the event window; indexing the bounds keeps
        # the week/day lookups cheap.
        Index("ix_events_start_at", "start_at"),
        Index("ix_events_end_at", "end_at"),
    )


class EventAttendee(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "event_attendees"

    event_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"), nullable=False
    )
    # External guests are tracked by email only — no user account required.
    email: Mapped[str] = mapped_column(String(320), nullable=False)

    event: Mapped["Event"] = relationship(back_populates="attendees")

    __table_args__ = (
        UniqueConstraint("event_id", "email", name="uq_event_attendees_event_email"),
        Index("ix_event_attendees_event_id", "event_id"),
    )
