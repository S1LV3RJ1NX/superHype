"""Post controller: per-post listing, editing, and the approve/skip actions.

Enforces the fine-grained rule that a participant acts only on their own post
(admins may act on any). Approval pushes the publish to the worker.
"""

import uuid

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.post import Post
from app.models.user import User
from app.repositories import audit_repo
from app.repositories.campaign_repo import campaign_repo
from app.repositories.post_repo import post_repo
from app.schemas.common import Page, PageParams
from app.schemas.post import PostOut, PostUpdate
from app.services import campaign_service
from app.workers import queue


def _is_admin(user: User) -> bool:
    return user.role == "admin"


async def _load_or_404(db: AsyncSession, post_id: uuid.UUID) -> Post:
    post = await post_repo.get(db, post_id)
    if post is None:
        raise HTTPException(404, "Post not found.")
    return post


def _require_owner_or_admin(post: Post, user: User) -> None:
    if not (_is_admin(user) or post.user_id == user.id):
        raise HTTPException(403, "You can only act on your own posts.")


async def list_posts(
    db: AsyncSession, campaign_id: uuid.UUID, params: PageParams, user: User
) -> Page[PostOut]:
    campaign = await campaign_repo.get(db, campaign_id)
    if campaign is None:
        raise HTTPException(404, "Campaign not found.")
    if not (_is_admin(user) or campaign.created_by == user.id):
        posts = await post_repo.list_for_campaign(db, campaign_id)
        if not any(p.user_id == user.id for p in posts):
            raise HTTPException(403, "You do not have access to this campaign.")
    page = await post_repo.paginate_for_campaign(
        db, params=params, campaign_id=campaign_id
    )
    return Page[PostOut](
        items=[PostOut.model_validate(p) for p in page.items],
        next_cursor=page.next_cursor,
    )


async def update_post(
    db: AsyncSession, post_id: uuid.UUID, body: PostUpdate, actor: User
) -> PostOut:
    post = await _load_or_404(db, post_id)
    _require_owner_or_admin(post, actor)
    if post.status not in ("pending", "scheduled"):
        raise HTTPException(409, "Only pending posts can be edited.")
    updates = body.model_dump(exclude_unset=True)
    if updates:
        await post_repo.update(db, post, **updates)
        await audit_repo.record(
            db,
            actor_id=actor.id,
            action="post_edited",
            campaign_id=post.campaign_id,
            post_id=post.id,
            detail={"fields": sorted(updates.keys())},
        )
        await db.commit()
        await db.refresh(post)
    return PostOut.model_validate(post)


async def approve_post(db: AsyncSession, post_id: uuid.UUID, actor: User) -> PostOut:
    post = await _load_or_404(db, post_id)
    _require_owner_or_admin(post, actor)
    if post.status not in ("pending", "scheduled"):
        raise HTTPException(409, "Only pending posts can be approved.")
    post.status = "approved"
    await audit_repo.record(
        db,
        actor_id=actor.id,
        action="post_approved",
        campaign_id=post.campaign_id,
        post_id=post.id,
    )
    await db.commit()
    await queue.enqueue_job("publish_post", str(post.id))
    await db.refresh(post)
    return PostOut.model_validate(post)


async def skip_post(db: AsyncSession, post_id: uuid.UUID, actor: User) -> PostOut:
    post = await _load_or_404(db, post_id)
    _require_owner_or_admin(post, actor)
    if post.status not in ("pending", "scheduled"):
        raise HTTPException(409, "Only pending posts can be skipped.")
    post.status = "skipped"
    await audit_repo.record(
        db,
        actor_id=actor.id,
        action="post_skipped",
        campaign_id=post.campaign_id,
        post_id=post.id,
    )
    await campaign_service.check_completion(db, post.campaign_id)
    await db.commit()
    await db.refresh(post)
    return PostOut.model_validate(post)
