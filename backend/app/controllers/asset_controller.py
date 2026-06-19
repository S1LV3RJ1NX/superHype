"""Asset controller: validate and store uploaded images, and fetch them back."""

import uuid

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.safe_fetch import MAX_IMAGE_BYTES, is_allowed_image_type
from app.models.user import User
from app.repositories import audit_repo
from app.storage import db_asset_store


async def upload_asset(
    db: AsyncSession, *, data: bytes, content_type: str | None, actor: User
) -> uuid.UUID:
    if not is_allowed_image_type(content_type):
        raise HTTPException(415, "Only PNG, JPEG, GIF, or WebP images are allowed.")
    if len(data) == 0:
        raise HTTPException(400, "Empty upload.")
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(413, "Image exceeds the 8 MB limit.")
    normalized = content_type.split(";")[0].strip().lower()  # type: ignore[union-attr]
    asset_id = await db_asset_store.put(
        db, data=data, content_type=normalized, created_by=actor.id
    )
    await audit_repo.record(
        db,
        actor_id=actor.id,
        action="asset_uploaded",
        detail={
            "asset_id": str(asset_id),
            "content_type": normalized,
            "size": len(data),
        },
    )
    await db.commit()
    return asset_id


async def get_asset(db: AsyncSession, asset_id: uuid.UUID) -> tuple[bytes, str]:
    try:
        return await db_asset_store.get(db, asset_id)
    except KeyError as exc:
        raise HTTPException(404, "Asset not found.") from exc
