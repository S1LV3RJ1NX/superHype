"""Posts router: campaign post listing and the per-post approve/skip/edit actions."""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.controllers import post_controller
from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.common import Page, PageParams
from app.schemas.post import BatchAction, PostOut, PostUpdate

router = APIRouter(tags=["posts"])


@router.get("/v1/campaigns/{campaign_id}/posts", response_model=Page[PostOut])
async def list_posts(
    campaign_id: uuid.UUID,
    params: PageParams = Depends(),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Page[PostOut]:
    return await post_controller.list_posts(db, campaign_id, params, user)


# Literal path, declared before the /v1/posts/{post_id} routes so "batch" is not
# parsed as a post id. Settles several posts (the combined like+comment card) in
# one atomic request.
@router.post("/v1/posts/batch", response_model=list[PostOut])
async def batch_action(
    body: BatchAction,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> list[PostOut]:
    return await post_controller.batch_action(
        db, op=body.op, post_ids=body.post_ids, actor=actor
    )


@router.patch("/v1/posts/{post_id}", response_model=PostOut)
async def update_post(
    post_id: uuid.UUID,
    body: PostUpdate,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> PostOut:
    return await post_controller.update_post(db, post_id, body, actor)


@router.post("/v1/posts/{post_id}/approve", response_model=PostOut)
async def approve_post(
    post_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> PostOut:
    return await post_controller.approve_post(db, post_id, actor)


@router.post("/v1/posts/{post_id}/ack", response_model=PostOut)
async def acknowledge_post(
    post_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> PostOut:
    return await post_controller.acknowledge_post(db, post_id, actor)


@router.post("/v1/posts/{post_id}/skip", response_model=PostOut)
async def skip_post(
    post_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> PostOut:
    return await post_controller.skip_post(db, post_id, actor)
