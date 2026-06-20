"""Post controller: per-post listing, editing, and the approve/skip actions.

Enforces the fine-grained rule that a participant acts only on their own post
(admins may act on any). Approval pushes the publish to the worker.
"""

import uuid
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.post import Post
from app.models.user import User
from app.repositories import audit_repo
from app.repositories.campaign_repo import campaign_repo
from app.repositories.post_repo import post_repo
from app.repositories.social_account_repo import social_account_repo
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

    # Pre-check the publishing account so we never approve against a dying token.
    # Only the post owner can re-consent, so the proactive reconnect-then-act gate
    # applies to them; an admin acting on another user's post falls back to the
    # reactive 401 path (mark stale + request_reconnect) at publish time.
    account = await social_account_repo.get_by_user(db, post.user_id)
    if actor.id == post.user_id and (
        account is None
        or account.needs_reconnect(
            now=datetime.now(UTC),
            buffer_hours=settings.LINKEDIN_RECONNECT_BUFFER_HOURS,
        )
    ):
        raise HTTPException(
            409,
            detail={
                "code": "linkedin_reconnect_required",
                "post_id": str(post.id),
            },
        )

    # Backfill the publishing account if the post was planned before the owner
    # connected, so the worker can resolve a live token.
    if post.social_account_id is None and account is not None:
        post.social_account_id = account.id

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
