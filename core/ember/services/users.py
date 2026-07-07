import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ember.models import UserPreferences
from ember.schemas.users import PreferencesUpdateRequest


async def get_preferences(
    session: AsyncSession, user_id: uuid.UUID, workspace_id: uuid.UUID
) -> UserPreferences:
    preferences = (
        await session.execute(
            select(UserPreferences).where(
                UserPreferences.user_id == user_id,
                UserPreferences.workspace_id == workspace_id,
            )
        )
    ).scalar_one_or_none()

    if preferences is None:
        # Every workspace membership is created together with a preferences row
        # (see create_workspace); this only backfills members added before that
        # pairing existed.
        preferences = UserPreferences(user_id=user_id, workspace_id=workspace_id)
        session.add(preferences)
        await session.flush()
        await session.refresh(preferences)

    return preferences


async def update_preferences(
    session: AsyncSession,
    user_id: uuid.UUID,
    workspace_id: uuid.UUID,
    data: PreferencesUpdateRequest,
) -> UserPreferences:
    preferences = await get_preferences(session, user_id, workspace_id)

    if data.locale is not None:
        preferences.locale = data.locale
    if data.timezone is not None:
        preferences.timezone = data.timezone
    if data.week_starts_on is not None:
        preferences.week_starts_on = data.week_starts_on
    if data.work_day_start is not None:
        preferences.work_day_start = data.work_day_start
    if data.work_day_end is not None:
        preferences.work_day_end = data.work_day_end
    if data.time_format is not None:
        preferences.time_format = data.time_format

    # A partial update touching only one work-hour bound is validated here
    # against the other stored bound, so we return 422 instead of tripping the
    # DB check constraint (which would surface as a 500).
    if preferences.work_day_start >= preferences.work_day_end:
        raise HTTPException(
            status_code=422,
            detail="work_day_start must be before work_day_end",
        )

    await session.flush()
    await session.refresh(preferences)
    return preferences
