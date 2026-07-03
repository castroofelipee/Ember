from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from ember.db import get_db
from ember.schemas.auth import SignupRequest, SignupResponse
from ember.services.auth import EmailAlreadyRegisteredError, signup

router = APIRouter(prefix="/api/auth", tags=["Authentication"])


@router.post("/signup", status_code=status.HTTP_201_CREATED)
async def register(data: SignupRequest, db: AsyncSession = Depends(get_db)) -> SignupResponse:
    try:
        user = await signup(db, data)
    except EmailAlreadyRegisteredError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists.",
        ) from exc
    return SignupResponse.model_validate(user)
