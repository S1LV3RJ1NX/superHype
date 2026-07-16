"""Social connection endpoints (LinkedIn and X): list, authorize, callback,
reconnect, disconnect."""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.controllers import connection_controller
from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.connection import (
    AuthorizeUrlOut,
    ConnectionOut,
    OAuthCallbackBody,
)

router = APIRouter(prefix="/v1/connections", tags=["connections"])


@router.get("", response_model=list[ConnectionOut])
async def list_connections(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[ConnectionOut]:
    return await connection_controller.list_connections(db, user)


@router.get("/linkedin/authorize", response_model=AuthorizeUrlOut)
async def authorize_linkedin(
    resume_post_id: uuid.UUID | None = None,
    user: User = Depends(get_current_user),
) -> AuthorizeUrlOut:
    return await connection_controller.authorize_linkedin(user, resume_post_id)


@router.post("/linkedin/callback", response_model=ConnectionOut)
async def linkedin_callback(
    body: OAuthCallbackBody,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ConnectionOut:
    return await connection_controller.complete_linkedin(
        db, user, body.code, body.state
    )


@router.post("/linkedin/reconnect", response_model=AuthorizeUrlOut)
async def reconnect_linkedin(
    resume_post_id: uuid.UUID | None = None,
    user: User = Depends(get_current_user),
) -> AuthorizeUrlOut:
    return await connection_controller.authorize_linkedin(user, resume_post_id)


@router.delete("/linkedin", status_code=204)
async def disconnect_linkedin(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    await connection_controller.disconnect_linkedin(db, user)


@router.get("/x/authorize", response_model=AuthorizeUrlOut)
async def authorize_x(
    resume_post_id: uuid.UUID | None = None,
    user: User = Depends(get_current_user),
) -> AuthorizeUrlOut:
    return await connection_controller.authorize_x(user, resume_post_id)


@router.post("/x/callback", response_model=ConnectionOut)
async def x_callback(
    body: OAuthCallbackBody,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ConnectionOut:
    return await connection_controller.complete_x(db, user, body.code, body.state)


@router.post("/x/reconnect", response_model=AuthorizeUrlOut)
async def reconnect_x(
    resume_post_id: uuid.UUID | None = None,
    user: User = Depends(get_current_user),
) -> AuthorizeUrlOut:
    return await connection_controller.authorize_x(user, resume_post_id)


@router.delete("/x", status_code=204)
async def disconnect_x(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    await connection_controller.disconnect_x(db, user)
