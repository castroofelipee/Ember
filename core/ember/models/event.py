import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY
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

    # Recurrence: null recurrence_freq means a one-off event. When set, this
    # row is the recurring series' "master" and occurrences are expanded at
    # query time (see services.events._expand_occurrences) rather than
    # materialized as rows.
    recurrence_freq: Mapped[str | None] = mapped_column(String(10), nullable=True)
    recurrence_interval: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    # Weekly only: 0=Monday..6=Sunday. Null means "repeat on the start date's weekday".
    recurrence_by_weekday: Mapped[list[int] | None] = mapped_column(
        ARRAY(SmallInteger), nullable=True
    )
    # At most one of these is set (enforced in the request schema): an
    # occurrence-count limit, or a hard end date. Neither set means "never ends".
    recurrence_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    recurrence_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    recurrence_exdates: Mapped[list[datetime] | None] = mapped_column(
        ARRAY(DateTime(timezone=True)), nullable=True
    )

    attendees: Mapped[list["EventAttendee"]] = relationship(
        back_populates="event",
        cascade="all, delete-orphan",
        order_by="EventAttendee.email",
    )

    @property
    def recurrence(self) -> dict | None:
        """Shape the recurrence columns into the nested object EventResponse
        expects, or None for a one-off event."""
        if self.recurrence_freq is None:
            return None
        return {
            "freq": self.recurrence_freq,
            "interval": self.recurrence_interval,
            "by_weekday": self.recurrence_by_weekday,
            "count": self.recurrence_count,
            "until": self.recurrence_until,
        }

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
