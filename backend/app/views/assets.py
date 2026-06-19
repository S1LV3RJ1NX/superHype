"""Assets router: upload an image (editor+) and serve it back for previews."""

import uuid

from fastapi import APIRouter, Depends, File, Response, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.controllers import asset_controller
from app.core.deps import get_current_user, require_role
from app.db.session import get_db
from app.models.user import User

router = APIRouter(prefix="/v1/assets", tags=["assets"])


@router.post("", status_code=201)
async def upload_asset(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_role("editor")),
) -> dict[str, str]:
    data = await file.read()
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
