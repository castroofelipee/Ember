import uuid
from dataclasses import dataclass
from datetime import datetime

from dateutil.rrule import DAILY, FR, MO, MONTHLY, SA, SU, TH, TU, WE, WEEKLY, YEARLY, rrule
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ember.models import Calendar, Event, EventAttendee
from ember.schemas.events import EventCreateRequest

_FREQ_MAP = {"DAILY": DAILY, "WEEKLY": WEEKLY, "MONTHLY": MONTHLY, "YEARLY": YEARLY}
# 0=Monday..6=Sunday, matching RecurrenceRule.by_weekday.
_WEEKDAY_MAP = [MO, TU, WE, TH, FR, SA, SU]


@dataclass
class EventOccurrence:
    """A single expanded instance of a recurring event. Not a DB row — the
    series lives as one `Event` "master" row and instances are computed at
    read time so editing the recurrence rule doesn't require rewriting rows."""

    id: uuid.UUID
    calendar_id: uuid.UUID
    title: str
    description: str | None
    location: str | None
    start_at: datetime
    end_at: datetime
    all_day: bool
    color: str | None
    attendees: list[EventAttendee]
    recurrence: dict | None


async def create_event(
    session: AsyncSession, calendar_id: uuid.UUID, data: EventCreateRequest
) -> Event:
    recurrence = data.recurrence
    event = Event(
        calendar_id=calendar_id,
        title=data.title,
        description=data.description,
        location=data.location,
        start_at=data.start_at,
        end_at=data.end_at,
        all_day=data.all_day,
        color=data.color,
        attendees=[EventAttendee(email=email) for email in data.attendees],
        recurrence_freq=recurrence.freq if recurrence else None,
        recurrence_interval=recurrence.interval if recurrence else 1,
        recurrence_by_weekday=recurrence.by_weekday if recurrence else None,
        recurrence_count=recurrence.count if recurrence else None,
        recurrence_until=recurrence.until if recurrence else None,
    )
    session.add(event)
    await session.flush()
    # Re-load with attendees eagerly so serialization doesn't lazy-load on an
    # async session (which would raise).
    return await get_event(session, event.id)


async def get_event(session: AsyncSession, event_id: uuid.UUID) -> Event:
    return (
        await session.execute(
            select(Event).where(Event.id == event_id).options(selectinload(Event.attendees))
        )
    ).scalar_one()


async def get_event_or_none(session: AsyncSession, event_id: uuid.UUID) -> Event | None:
    return (
        await session.execute(select(Event).where(Event.id == event_id))
    ).scalar_one_or_none()


async def delete_event(session: AsyncSession, event: Event) -> None:
    await session.delete(event)
    await session.flush()


def _expand_occurrences(
    event: Event, range_start: datetime, range_end: datetime
) -> list[EventOccurrence]:
    """Instances of a recurring `event` that overlap [range_start, range_end)."""
    duration = event.end_at - event.start_at
    kwargs: dict = {
        "freq": _FREQ_MAP[event.recurrence_freq],
        "interval": event.recurrence_interval or 1,
        "dtstart": event.start_at,
    }
    if event.recurrence_by_weekday:
        kwargs["byweekday"] = [_WEEKDAY_MAP[day] for day in event.recurrence_by_weekday]
    if event.recurrence_count:
        kwargs["count"] = event.recurrence_count
    elif event.recurrence_until:
        kwargs["until"] = event.recurrence_until
    else:
        # Unbounded ("never ends") — cap the expansion at the query window so
        # it doesn't run away generating occurrences past what's on screen.
        kwargs["until"] = range_end

    occurrences: list[EventOccurrence] = []
    for occ_start in rrule(**kwargs):
        if occ_start >= range_end:
            break
        occ_end = occ_start + duration
        if occ_end > range_start:
            occurrences.append(
                EventOccurrence(
                    id=event.id,
                    calendar_id=event.calendar_id,
                    title=event.title,
                    description=event.description,
                    location=event.location,
                    start_at=occ_start,
                    end_at=occ_end,
                    all_day=event.all_day,
                    color=event.color,
                    attendees=event.attendees,
                    recurrence=event.recurrence,
                )
            )
    return occurrences


async def list_events_in_range(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    range_start: datetime,
    range_end: datetime,
) -> list[Event | EventOccurrence]:
    """Events in the workspace's calendars that overlap [range_start, range_end).
    A one-off event overlaps when it starts before the window ends and ends
    after the window starts. A recurring event's master row is fetched if any
    of its occurrences could fall in the window, then expanded in Python."""
    rows = (
        (
            await session.execute(
                select(Event)
                .join(Calendar, Calendar.id == Event.calendar_id)
                .where(
                    Calendar.workspace_id == workspace_id,
                    Event.start_at < range_end,
                    or_(
                        and_(Event.recurrence_freq.is_(None), Event.end_at > range_start),
                        and_(
                            Event.recurrence_freq.isnot(None),
                            or_(
                                Event.recurrence_until.is_(None),
                                Event.recurrence_until >= range_start,
                            ),
                        ),
                    ),
                )
                .order_by(Event.start_at)
                .options(selectinload(Event.attendees))
            )
        )
        .scalars()
        .all()
    )

    items: list[Event | EventOccurrence] = []
    for event in rows:
        if event.recurrence_freq is None:
            items.append(event)
        else:
            items.extend(_expand_occurrences(event, range_start, range_end))

    items.sort(key=lambda item: item.start_at)
    return items
