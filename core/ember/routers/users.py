import uuid

import cloudinary
import cloudinary.uploader
from cloudinary.utils import cloudinary_url
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.ext.asyncio import AsyncSession

from ember.config import env
from ember.db import get_db
from ember.dependencies import get_current_user
from ember.images import MAX_IMAGE_BYTES, configure_cloudinary
from ember.models import User
from ember.schemas.users import CurrentUserResponse

router = APIRouter(prefix="/api/users", tags=["Users"])

# Profile photos are shown at avatar sizes only, so they are stored already
# cropped to a square around the face rather than at whatever the camera gave us.
AVATAR_SIZE = 256


def avatar_public_id(user_id: uuid.UUID) -> str:
    """One fixed id per account, so a new photo overwrites the old one instead
    of leaving an orphan behind in Cloudinary."""
    return f"ember/users/{user_id}/avatar"


@router.get("/me")
async def read_current_user(user: User = Depends(get_current_user)) -> CurrentUserResponse:
    return CurrentUserResponse.model_validate(user)


@router.post("/me/avatar")
async def upload_avatar(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CurrentUserResponse:
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=415, detail="The profile photo must be an image.")
    contents = await file.read(MAX_IMAGE_BYTES + 1)
    if len(contents) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="Profile photo must be 10 MB or smaller.")
    if not env["CLOUDINARY_URL"]:
        raise HTTPException(status_code=503, detail="Image uploads are not configured.")
    configure_cloudinary()
    result = await run_in_threadpool(
        cloudinary.uploader.upload,
        contents,
        public_id=avatar_public_id(user.id),
        resource_type="image",
        overwrite=True,
        invalidate=True,
    )
    # Because the public id never changes, the URL would too — and every cache
    # between here and the browser would keep serving the previous photo. The
    # version Cloudinary just returned is what makes each upload a new URL.
    avatar_url, _ = cloudinary_url(
        result["public_id"],
        version=result.get("version"),
        width=AVATAR_SIZE,
        height=AVATAR_SIZE,
        crop="fill",
        gravity="face",
        fetch_format="auto",
        quality="auto",
        secure=True,
    )
    user.avatar_url = avatar_url
    await db.flush()
    return CurrentUserResponse.model_validate(user)
