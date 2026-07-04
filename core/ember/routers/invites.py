from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from ember.db import get_db
from ember.dependencies import get_current_user
from ember.models import User
from ember.schemas.invites import InviteCreateResponse
from ember.services.invites import create_invite

router = APIRouter(prefix="/api/invites", tags=["Invites"])


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_invite_route(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> InviteCreateResponse:
    invite, raw_code = await create_invite(db, current_user.id)
    return InviteCreateResponse(code=raw_code, expires_at=invite.expires_at)
