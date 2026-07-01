"""Assets router: upload an image or short video (editor+) and serve it back."""

import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.controllers import asset_controller
from app.core.deps import get_current_user, require_role
from app.core.safe_fetch import MAX_IMAGE_BYTES, media_kind
from app.db.session import get_db
from app.models.user import User

router = APIRouter(prefix="/v1/assets", tags=["assets"])

_READ_CHUNK = 1024 * 1024


async def _read_capped(file: UploadFile, max_bytes: int, noun: str) -> bytes:
    """Read the upload in chunks, aborting once it exceeds max_bytes.

    Bounds peak memory to roughly max_bytes: a hostile client cannot make the
    worker buffer an arbitrarily large body before the size check runs.
    """
    chunks: list[bytes] = []
    total = 0
    while chunk := await file.read(_READ_CHUNK):
        total += len(chunk)
        if total > max_bytes:
            mb = max_bytes // (1024 * 1024)
            raise HTTPException(413, f"{noun} exceeds the {mb} MB limit.")
        chunks.append(chunk)
    return b"".join(chunks)


@router.post("", status_code=201)
async def upload_asset(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_role("editor")),
) -> dict[str, str]:
    # Decide the cap from the declared type before reading, so an oversized body
    # is rejected mid-stream instead of fully buffered. The controller re-checks
    # the type and size as the authoritative guard.
    kind = media_kind(file.content_type)
    if kind is None:
        raise HTTPException(
            415,
            "Only PNG, JPEG, GIF, or WebP images or MP4/MOV video are allowed.",
        )
    if kind == "image":
        max_bytes, noun = MAX_IMAGE_BYTES, "Image"
    else:
        max_bytes, noun = settings.MAX_VIDEO_BYTES, "Video"
    data = await _read_capped(file, max_bytes, noun)
    asset_id = await asset_controller.upload_asset(
        db, data=data, content_type=file.content_type, actor=actor
    )
    return {"id": str(asset_id)}


@router.get("/{asset_id}")
async def get_asset(
    asset_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> Response:
    data, content_type = await asset_controller.get_asset(db, asset_id)
    return Response(
        content=data,
        media_type=content_type,
        headers={
            "Cache-Control": "private, max-age=3600",
            "X-Content-Type-Options": "nosniff",
        },
    )
