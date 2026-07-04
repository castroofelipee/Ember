from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ember.db import get_db
from ember.dependencies import get_current_user
from ember.models import User
from ember.schemas.users import PreferencesResponse, PreferencesUpdateRequest
from ember.services.users import get_preferences, update_preferences

router = APIRouter(prefix="/api/users", tags=["Users"])


@router.get("/me/preferences")
async def get_my_preferences(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PreferencesResponse:
    preferences = await get_preferences(db, current_user.id)
    return PreferencesResponse.model_validate(preferences)


@router.patch("/me/preferences")
async def update_my_preferences(
    data: PreferencesUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PreferencesResponse:
    preferences = await update_preferences(db, current_user.id, data)
    return PreferencesResponse.model_validate(preferences)
