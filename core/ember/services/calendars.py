import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ember.models import Calendar
from ember.schemas.calendars import DEFAULT_CALENDAR_COLOR, CalendarCreateRequest


async def create_calendar(
    session: AsyncSession, workspace_id: uuid.UUID, data: CalendarCreateRequest
) -> Calendar:
    calendar = Calendar(
        workspace_id=workspace_id,
        name=data.name,
        color=data.color or DEFAULT_CALENDAR_COLOR,
    )
    session.add(calendar)
    await session.flush()
    return calendar


async def get_calendar(session: AsyncSession, calendar_id: uuid.UUID) -> Calendar | None:
    return await session.get(Calendar, calendar_id)


async def list_calendars(session: AsyncSession, workspace_id: uuid.UUID) -> list[Calendar]:
    return (
        (
            await session.execute(
                select(Calendar)
                .where(Calendar.workspace_id == workspace_id)
                .order_by(Calendar.created_at)
            )
        )
        .scalars()
        .all()
    )
