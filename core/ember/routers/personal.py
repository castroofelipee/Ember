import uuid
from datetime import date
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.concurrency import run_in_threadpool
import cloudinary
import cloudinary.uploader
from cloudinary.utils import cloudinary_url
from urllib.parse import urlparse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ember.db import get_db
from ember.dependencies import get_current_user
from ember.models import User
from ember.models.personal import PersonalItem, PersonalItemKind
from ember.schemas.personal import PersonalItemCreate, PersonalItemResponse, PersonalItemUpdate
from ember.config import env

router = APIRouter(prefix="/api/personal", tags=["Personal Space"])
MAX_IMAGE_BYTES = 10 * 1024 * 1024


def configure_cloudinary() -> None:
    parsed = urlparse(env["CLOUDINARY_URL"])
    if parsed.scheme != "cloudinary" or not all(
        (parsed.hostname, parsed.username, parsed.password)
    ):
        raise HTTPException(status_code=503, detail="Image uploads are not configured.")
    cloudinary.config(
        cloud_name=parsed.hostname,
        api_key=parsed.username,
        api_secret=parsed.password,
        secure=True,
    )


async def owned(db: AsyncSession, item_id: uuid.UUID, user_id: uuid.UUID) -> PersonalItem:
    item = (
        await db.execute(
            select(PersonalItem).where(PersonalItem.id == item_id, PersonalItem.user_id == user_id)
        )
    ).scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="Not found.")
    return item


@router.get("/items")
async def list_items(
    kind: PersonalItemKind | None = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[PersonalItemResponse]:
    query = select(PersonalItem).where(PersonalItem.user_id == user.id)
    if kind:
        query = query.where(PersonalItem.kind == kind)
    return list((await db.execute(query.order_by(PersonalItem.created_at.desc()))).scalars())


@router.post("/items", status_code=status.HTTP_201_CREATED)
async def create_item(
    data: PersonalItemCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PersonalItemResponse:
    item = PersonalItem(user_id=user.id, kind=data.kind, title=data.title, data=data.data)
    db.add(item)
    await db.flush()
    await db.refresh(item)
    return item


@router.post("/vision/upload", status_code=status.HTTP_201_CREATED)
async def upload_vision_image(
    wall_id: uuid.UUID = Form(...),
    title: str = Form(default=""),
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PersonalItemResponse:
    wall = await owned(db, wall_id, user.id)
    if wall.kind != PersonalItemKind.VISION or wall.data.get("type") != "wall":
        raise HTTPException(status_code=404, detail="Vision wall not found.")
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=415, detail="Only image files are supported.")
    contents = await file.read(MAX_IMAGE_BYTES + 1)
    if len(contents) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="Image must be 10 MB or smaller.")
    if not env["CLOUDINARY_URL"]:
        raise HTTPException(status_code=503, detail="Image uploads are not configured.")
    configure_cloudinary()
    result = await run_in_threadpool(
        cloudinary.uploader.upload,
        contents,
        folder=f"ember/personal/{user.id}",
        resource_type="image",
        quality="auto",
    )
    optimized_url, _ = cloudinary_url(
        result["public_id"], fetch_format="auto", quality="auto", secure=True
    )
    item = PersonalItem(
        user_id=user.id,
        kind=PersonalItemKind.VISION,
        title=title.strip() or file.filename or "Inspiration",
        data={
            "type": "image",
            "wall_id": str(wall.id),
            "image_url": optimized_url,
            "public_id": result["public_id"],
            "width": result.get("width"),
            "height": result.get("height"),
        },
    )
    db.add(item)
    await db.flush()
    await db.refresh(item)
    return item


@router.post("/readings", status_code=status.HTTP_201_CREATED)
async def create_reading(
    title: str = Form(..., min_length=1, max_length=240),
    author: str = Form(..., min_length=1, max_length=240),
    genre: str = Form(default="", max_length=120),
    shelf: str = Form(default="reading"),
    started_at: date | None = Form(default=None),
    finished_at: date | None = Form(default=None),
    pages_read: int = Form(default=0, ge=0),
    total_pages: int = Form(default=0, ge=0),
    rating: int = Form(default=0, ge=0, le=5),
    cover: UploadFile | None = File(default=None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PersonalItemResponse:
    if shelf not in {"reading", "finished", "want_to_read"}:
        raise HTTPException(status_code=422, detail="Invalid reading shelf.")
    if pages_read > total_pages and total_pages > 0:
        raise HTTPException(status_code=422, detail="Pages read cannot exceed total pages.")
    if total_pages == 0 and pages_read > 0:
        raise HTTPException(status_code=422, detail="Add total pages before recording progress.")
    if finished_at is not None and started_at is not None and finished_at < started_at:
        raise HTTPException(status_code=422, detail="Finish date cannot be before start date.")

    cover_url = None
    public_id = None
    if cover is not None:
        if not cover.content_type or not cover.content_type.startswith("image/"):
            raise HTTPException(status_code=415, detail="The book cover must be an image.")
        contents = await cover.read(MAX_IMAGE_BYTES + 1)
        if len(contents) > MAX_IMAGE_BYTES:
            raise HTTPException(status_code=413, detail="Book cover must be 10 MB or smaller.")
        if not env["CLOUDINARY_URL"]:
            raise HTTPException(status_code=503, detail="Image uploads are not configured.")
        configure_cloudinary()
        result = await run_in_threadpool(
            cloudinary.uploader.upload,
            contents,
            folder=f"ember/personal/{user.id}/readings",
            resource_type="image",
        )
        public_id = result["public_id"]
        cover_url, _ = cloudinary_url(public_id, fetch_format="auto", quality="auto", secure=True)

    completed = (
        shelf == "finished"
        or finished_at is not None
        or (total_pages > 0 and pages_read == total_pages)
    )
    reading_status = (
        "want_to_read" if shelf == "want_to_read" else ("finished" if completed else "reading")
    )
    item = PersonalItem(
        user_id=user.id,
        kind=PersonalItemKind.READING,
        title=title.strip(),
        data={
            "author": author.strip(),
            "genre": genre.strip(),
            "started_at": started_at.isoformat() if started_at else None,
            "finished_at": (finished_at or (date.today() if completed else None)).isoformat()
            if (finished_at or completed)
            else None,
            "pages_read": pages_read,
            "total_pages": total_pages,
            "rating": rating,
            "status": reading_status,
            "cover_url": cover_url,
            "public_id": public_id,
        },
    )
    db.add(item)
    await db.flush()
    await db.refresh(item)
    return item


@router.patch("/items/{item_id}")
async def update_item(
    item_id: uuid.UUID,
    data: PersonalItemUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PersonalItemResponse:
    item = await owned(db, item_id, user.id)
    if data.title is not None:
        item.title = data.title.strip()
    if data.data is not None:
        item.data = data.data
    await db.flush()
    # `updated_at` is generated by the database on UPDATE. Refresh it while
    # still inside the async session so response serialization never attempts
    # an implicit (and unsupported) lazy query via MissingGreenlet.
    await db.refresh(item)
    return item


@router.delete("/items/{item_id}", status_code=204)
async def delete_item(
    item_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> None:
    item = await owned(db, item_id, user.id)
    if item.kind == PersonalItemKind.VISION and item.data.get("type") == "wall":
        images = list(
            (
                await db.execute(
                    select(PersonalItem).where(
                        PersonalItem.user_id == user.id,
                        PersonalItem.kind == PersonalItemKind.VISION,
                        PersonalItem.data["wall_id"].as_string() == str(item.id),
                    )
                )
            ).scalars()
        )
        if env["CLOUDINARY_URL"]:
            configure_cloudinary()
            for image in images:
                if image.data.get("public_id"):
                    await run_in_threadpool(cloudinary.uploader.destroy, image.data["public_id"])
        for image in images:
            await db.delete(image)
    public_id = item.data.get("public_id")
    if public_id and env["CLOUDINARY_URL"]:
        configure_cloudinary()
        await run_in_threadpool(cloudinary.uploader.destroy, public_id)
    await db.delete(item)
    await db.flush()
