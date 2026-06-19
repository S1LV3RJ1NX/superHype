"""LinkedIn connection endpoints: list, authorize, callback, reconnect, disconnect."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.controllers import connection_controller
from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.repositories.social_account_repo import social_account_repo
from app.schemas.connection import (
    AuthorizeUrlOut,
    ConnectionOut,
    LinkedInCallbackBody,
)

router = APIRouter(prefix="/v1/connections", tags=["connections"])


@router.get("", response_model=list[ConnectionOut])
async def list_connections(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[ConnectionOut]:
    accounts = await social_account_repo.list(db, user_id=user.id)
    return [ConnectionOut.model_validate(a) for a in accounts]


@router.get("/linkedin/authorize", response_model=AuthorizeUrlOut)
async def authorize_linkedin(
    user: User = Depends(get_current_user),
) -> AuthorizeUrlOut:
    return await connection_controller.authorize_linkedin(user)


@router.post("/linkedin/callback", response_model=ConnectionOut)
async def linkedin_callback(
    body: LinkedInCallbackBody,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ConnectionOut:
    return await connection_controller.complete_linkedin(
        db, user, body.code, body.state
    )


@router.post("/linkedin/reconnect", response_model=AuthorizeUrlOut)
async def reconnect_linkedin(
    user: User = Depends(get_current_user),
) -> AuthorizeUrlOut:
    return await connection_controller.authorize_linkedin(user)


@router.delete("/linkedin", status_code=204)
async def disconnect_linkedin(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    await connection_controller.disconnect_linkedin(db, user)
