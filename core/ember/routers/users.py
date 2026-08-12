from fastapi import APIRouter, Depends

from ember.dependencies import get_current_user
from ember.models import User
from ember.schemas.users import CurrentUserResponse

router = APIRouter(prefix="/api/users", tags=["Users"])


@router.get("/me")
async def read_current_user(user: User = Depends(get_current_user)) -> CurrentUserResponse:
    return CurrentUserResponse.model_validate(user)
