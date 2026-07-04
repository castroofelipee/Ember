import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ember.models import Calendar, Event, EventAttendee
from ember.schemas.events import EventCreateRequest


async def create_event(
    session: AsyncSession, calendar_id: uuid.UUID, data: EventCreateRequest
) -> Event:
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


async def list_events_in_range(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    range_start: datetime,
    range_end: datetime,
) -> list[Event]:
    """Events in the workspace's calendars that overlap [range_start, range_end).
    An event overlaps when it starts before the window ends and ends after the
    window starts."""
    return list(
        (
            await session.execute(
                select(Event)
                .join(Calendar, Calendar.id == Event.calendar_id)
                .where(
                    Calendar.workspace_id == workspace_id,
                    Event.start_at < range_end,
                    Event.end_at > range_start,
                )
                .order_by(Event.start_at)
                .options(selectinload(Event.attendees))
            )
        )
        .scalars()
        .all()
    )
