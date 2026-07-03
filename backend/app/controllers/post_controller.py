"""Post controller: per-post listing, editing, and the approve/skip actions.

The approve/ack/skip logic lives in ``services.approval_service`` (shared with the
Slack controller). This layer stays thin: it enforces access on reads/edits and
translates the service's transport-agnostic ``ApprovalError`` into HTTP responses.
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
from app.services import approval_service
from app.services.approval_service import (
    ApprovalError,
    CampaignNotFoundError,
    LaunchRequiredError,
    MixedCampaignError,
    NotOwnerError,
    NotOwnerOrAdminError,
    PostNotFoundError,
    ReconnectRequiredError,
)


def _is_admin(user: User) -> bool:
    return user.role == "admin"


async def _load_or_404(db: AsyncSession, post_id: uuid.UUID) -> Post:
    post = await post_repo.get(db, post_id)
    if post is None:
        raise HTTPException(404, "Post not found.")
    return post


async def _require_editor_of(db: AsyncSession, post: Post, user: User) -> None:
    """Who may edit a post's text: its owner, an admin, or the campaign creator.

    The creator drives the campaign, so they refine any participant's comment or
    reshare before launch; ownership still gates the act of approving/publishing.
    """
    if _is_admin(user) or post.user_id == user.id:
        return
    campaign = await campaign_repo.get(db, post.campaign_id)
    if campaign is not None and campaign.created_by == user.id:
        return
    raise HTTPException(
        403, "You can only edit your own posts or posts in a campaign you created."
    )


def _to_http(exc: ApprovalError) -> HTTPException:
    """Map a domain approval error to the HTTP response the API contract expects."""
    if isinstance(exc, PostNotFoundError):
        return HTTPException(404, "Post not found.")
    if isinstance(exc, CampaignNotFoundError):
        return HTTPException(404, "Campaign not found.")
    if isinstance(exc, NotOwnerError):
        return HTTPException(403, "Only the person asked can mark this action done.")
    if isinstance(exc, NotOwnerOrAdminError):
        return HTTPException(
            403, "Only the owner, the campaign creator, or an admin can do this."
        )
    if isinstance(exc, LaunchRequiredError):
        return HTTPException(409, "Launch the campaign before approving posts.")
    if isinstance(exc, ReconnectRequiredError):
        return HTTPException(
            409,
            detail={
                "code": "linkedin_reconnect_required",
                "post_id": str(exc.post_id),
            },
        )
    if isinstance(exc, MixedCampaignError):
        return HTTPException(400, "All posts must belong to the same campaign.")
    # InvalidStateError and any future ApprovalError default to a 409 conflict.
    return HTTPException(409, str(exc))


async def list_posts(
    db: AsyncSession, campaign_id: uuid.UUID, params: PageParams, user: User
) -> Page[PostOut]:
    campaign = await campaign_repo.get(db, campaign_id)
    if campaign is None:
        raise HTTPException(404, "Campaign not found.")
    # Admins and the creator see the whole plan; a plain participant sees only
    # their own posts and comments (the rows they can act on), never teammates'.
    scope_user_id: uuid.UUID | None = None
    if not (_is_admin(user) or campaign.created_by == user.id):
        if not await post_repo.exists_for_campaign_user(db, campaign_id, user.id):
            raise HTTPException(403, "You do not have access to this campaign.")
        scope_user_id = user.id
    page = await post_repo.paginate_for_campaign(
        db, params=params, campaign_id=campaign_id, user_id=scope_user_id
    )
    return Page[PostOut](
        items=[PostOut.model_validate(p) for p in page.items],
        next_cursor=page.next_cursor,
    )


async def update_post(
    db: AsyncSession, post_id: uuid.UUID, body: PostUpdate, actor: User
) -> PostOut:
    post = await _load_or_404(db, post_id)
    await _require_editor_of(db, post, actor)
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
    return PostOut.model_validate(post)


async def approve_post(db: AsyncSession, post_id: uuid.UUID, actor: User) -> PostOut:
    try:
        posts = await approval_service.approve(db, [post_id], actor)
    except ApprovalError as exc:
        raise _to_http(exc) from exc
    return PostOut.model_validate(posts[0])


async def acknowledge_post(
    db: AsyncSession, post_id: uuid.UUID, actor: User
) -> PostOut:
    """Owner marks an assisted-manual comment or like done after acting by hand.

    Only the person who was asked can acknowledge it: an admin cannot mark
    someone else's engagement done because only that person can actually act.
    """
    try:
        posts = await approval_service.acknowledge(db, [post_id], actor)
    except ApprovalError as exc:
        raise _to_http(exc) from exc
    return PostOut.model_validate(posts[0])


async def skip_post(db: AsyncSession, post_id: uuid.UUID, actor: User) -> PostOut:
    try:
        posts = await approval_service.skip(db, [post_id], actor)
    except ApprovalError as exc:
        raise _to_http(exc) from exc
    return PostOut.model_validate(posts[0])


async def batch_action(
    db: AsyncSession,
    *,
    op: str,
    post_ids: list[uuid.UUID],
    actor: User,
) -> list[PostOut]:
    """Settle several posts (approve, ack, or skip) in one atomic request.

    Backs the combined assisted like+comment card: one click settles both rows.
    Every post must belong to the same campaign; the same per-row guards and
    state checks as the single-post handlers apply, so a bad row rejects the
    whole batch before anything commits.
    """
    try:
        posts = await approval_service.batch(db, op=op, post_ids=post_ids, actor=actor)
    except ApprovalError as exc:
        raise _to_http(exc) from exc
    return [PostOut.model_validate(p) for p in posts]
