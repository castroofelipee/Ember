import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from ember.db import get_db
from ember.dependencies import get_current_user
from ember.models import User
from ember.schemas.calendars import CalendarCreateRequest, CalendarResponse
from ember.schemas.users import PreferencesResponse, PreferencesUpdateRequest
from ember.schemas.workspaces import WorkspaceCreateRequest, WorkspaceResponse
from ember.services.calendars import create_calendar, list_calendars
from ember.services.users import get_preferences, update_preferences
from ember.services.workspaces import (
    NotAWorkspaceMemberError,
    assert_workspace_member,
    create_workspace,
    list_my_workspaces,
)

router = APIRouter(prefix="/api/workspaces", tags=["Workspaces"])

_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found.")


async def _require_membership(db: AsyncSession, workspace_id: uuid.UUID, user_id: uuid.UUID) -> None:
    try:
        await assert_workspace_member(db, workspace_id, user_id)
    except NotAWorkspaceMemberError as exc:
        raise _NOT_FOUND from exc


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_workspace_route(
    data: WorkspaceCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkspaceResponse:
    workspace = await create_workspace(db, current_user.id, data)
    return WorkspaceResponse(
        id=workspace.id, name=workspace.name, role="owner", created_at=workspace.created_at
    )


@router.get("")
async def list_workspaces_route(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[WorkspaceResponse]:
    rows = await list_my_workspaces(db, current_user.id)
    return [
        WorkspaceResponse(id=w.id, name=w.name, role=role.value, created_at=w.created_at)
        for w, role in rows
    ]


@router.post("/{workspace_id}/calendars", status_code=status.HTTP_201_CREATED)
async def create_calendar_route(
    workspace_id: uuid.UUID,
    data: CalendarCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CalendarResponse:
    await _require_membership(db, workspace_id, current_user.id)
    calendar = await create_calendar(db, workspace_id, data)
    return CalendarResponse.model_validate(calendar)


@router.get("/{workspace_id}/calendars")
async def list_calendars_route(
    workspace_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[CalendarResponse]:
    await _require_membership(db, workspace_id, current_user.id)
    calendars = await list_calendars(db, workspace_id)
    return [CalendarResponse.model_validate(c) for c in calendars]


@router.get("/{workspace_id}/preferences")
async def get_workspace_preferences_route(
    workspace_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PreferencesResponse:
    await _require_membership(db, workspace_id, current_user.id)
    preferences = await get_preferences(db, current_user.id, workspace_id)
    return PreferencesResponse.model_validate(preferences)


@router.patch("/{workspace_id}/preferences")
async def update_workspace_preferences_route(
    workspace_id: uuid.UUID,
    data: PreferencesUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PreferencesResponse:
    await _require_membership(db, workspace_id, current_user.id)
    preferences = await update_preferences(db, current_user.id, workspace_id, data)
    return PreferencesResponse.model_validate(preferences)
