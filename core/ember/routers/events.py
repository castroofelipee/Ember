import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from ember.db import get_db
from ember.dependencies import get_current_user
from ember.models import User
from ember.schemas.events import EventCreateRequest, EventResponse
from ember.services.calendars import get_calendar
from ember.services.events import (
    create_event,
    delete_event,
    get_event_or_none,
    list_events_in_range,
)
from ember.services.workspaces import NotAWorkspaceMemberError, assert_workspace_member

router = APIRouter(prefix="/api", tags=["Events"])

_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")


async def _require_membership(db: AsyncSession, workspace_id: uuid.UUID, user_id: uuid.UUID) -> None:
    try:
        await assert_workspace_member(db, workspace_id, user_id)
    except NotAWorkspaceMemberError as exc:
        raise _NOT_FOUND from exc


@router.post("/calendars/{calendar_id}/events", status_code=status.HTTP_201_CREATED)
async def create_event_route(
    calendar_id: uuid.UUID,
    data: EventCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> EventResponse:
    calendar = await get_calendar(db, calendar_id)
    # Unknown calendar and calendar-in-another-workspace both read as 404 so a
    # non-member can't probe which calendar ids exist.
    if calendar is None:
        raise _NOT_FOUND
    await _require_membership(db, calendar.workspace_id, current_user.id)

    event = await create_event(db, calendar_id, data)
    return EventResponse.model_validate(event)


@router.get("/workspaces/{workspace_id}/events")
async def list_events_route(
    workspace_id: uuid.UUID,
    start: datetime = Query(..., description="Start of the window (inclusive)."),
    end: datetime = Query(..., description="End of the window (exclusive)."),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[EventResponse]:
    await _require_membership(db, workspace_id, current_user.id)
    events = await list_events_in_range(db, workspace_id, start, end)
    return [EventResponse.model_validate(event) for event in events]


@router.delete("/events/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_event_route(
    event_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    event = await get_event_or_none(db, event_id)
    if event is None:
        raise _NOT_FOUND
    calendar = await get_calendar(db, event.calendar_id)
    if calendar is None:
        raise _NOT_FOUND
    await _require_membership(db, calendar.workspace_id, current_user.id)
    await delete_event(db, event)
