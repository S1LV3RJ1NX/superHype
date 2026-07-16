"""Approval domain logic: approve, acknowledge, and skip posts.

Shared by the HTTP post controller and the Slack controller so the ownership
guards, state checks, and side effects (audit rows, completion, publish enqueue)
live in one place. Functions raise transport-agnostic ``ApprovalError``
subclasses; the caller maps them to an HTTP response or a Slack message. This
layer owns the transaction: each public function commits once.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.engagement import is_assisted
from app.core.platforms import platform_label
from app.models.post import Post
from app.models.user import User
from app.repositories import audit_repo
from app.repositories.campaign_repo import campaign_repo
from app.repositories.post_repo import post_repo
from app.repositories.social_account_repo import social_account_repo
from app.services import campaign_service
from app.workers import queue


class ApprovalError(Exception):
    """Base for approve/ack/skip domain failures (transport maps to HTTP/Slack)."""


class PostNotFoundError(ApprovalError):
    def __init__(self, post_id: uuid.UUID) -> None:
        self.post_id = post_id
        super().__init__("Post not found.")


class CampaignNotFoundError(ApprovalError):
    def __init__(self) -> None:
        super().__init__("Campaign not found.")


class NotOwnerError(ApprovalError):
    """Actor may not acknowledge this post (ack is owner-only)."""

    def __init__(self) -> None:
        super().__init__("Only the person asked can mark this action done.")


class NotOwnerOrAdminError(ApprovalError):
    """Actor is not the owner, campaign creator, or an admin (approve/skip)."""

    def __init__(self) -> None:
        super().__init__(
            "Only the owner, the campaign creator, or an admin can do this."
        )


class InvalidStateError(ApprovalError):
    """The post is not in a status this action allows."""


class LaunchRequiredError(ApprovalError):
    def __init__(self) -> None:
        super().__init__("Launch the campaign before approving posts.")


class ReconnectRequiredError(ApprovalError):
    """A non-assisted action needs a live platform token that is missing or stale."""

    def __init__(self, post_id: uuid.UUID, platform: str = "linkedin") -> None:
        self.post_id = post_id
        self.platform = platform
        super().__init__(f"{platform_label(platform)} reconnect required.")


class MixedCampaignError(ApprovalError):
    def __init__(self) -> None:
        super().__init__("All posts must belong to the same campaign.")


def _is_admin(user: User) -> bool:
    return user.role == "admin"


def _require_owner(post: Post, user: User) -> None:
    # Acknowledging an assisted ask means "I performed this like/comment by hand".
    # Only the person asked can truthfully do that, so ack stays owner-only even
    # for an admin.
    if post.user_id != user.id:
        raise NotOwnerError()


async def _require_owner_admin_or_creator(
    db: AsyncSession, post: Post, user: User
) -> None:
    """Approve/skip are open to the owner, an admin, or the campaign creator.

    The creator drives the campaign, so they (and admins) settle any
    participant's action for a whole domain at once (approve all comments, etc).
    A non-assisted action still publishes under the owner's own token, so if that
    token is missing or stale the reconnect gate rejects it and the owner must
    re-consent; approving on their behalf never bypasses that.
    """
    if _is_admin(user) or post.user_id == user.id:
        return
    campaign = await campaign_repo.get(db, post.campaign_id)
    if campaign is not None and campaign.created_by == user.id:
        return
    raise NotOwnerOrAdminError()


async def _apply_approve(db: AsyncSession, post: Post, actor: User) -> bool:
    """Validate and mutate one post to ``approved`` in place. No commit or enqueue.

    Returns whether this was a retry (a failed post being re-approved).
    """
    await _require_owner_admin_or_creator(db, post, actor)
    # "failed" is allowed so the owner can retry after fixing the cause (e.g. a
    # stale token that they have since reconnected). Retry reuses this whole path
    # including the reconnect gate; publish_post is idempotent so a retry never
    # double-posts.
    is_retry = post.status == "failed"
    if post.status not in ("pending", "scheduled", "failed"):
        raise InvalidStateError("Only pending or failed posts can be approved.")

    # Launch is compulsory: nothing publishes until the campaign is launched.
    campaign = await campaign_repo.get(db, post.campaign_id)
    if campaign is None:
        raise CampaignNotFoundError()
    if campaign.launched_at is None:
        raise LaunchRequiredError()

    # Assisted-manual comments and likes (LinkedIn only) are done by the person
    # in their own browser, not through our token, so they skip the account and
    # reconnect gate entirely. Posts and reshares (and every X action, which is
    # fully automated) still publish under the owner's token.
    if not is_assisted(post.action, post.platform):
        account = await social_account_repo.get_by_user(
            db, post.user_id, platform=post.platform
        )
        buffer_hours = (
            settings.X_RECONNECT_BUFFER_HOURS
            if post.platform == "x"
            else settings.LINKEDIN_RECONNECT_BUFFER_HOURS
        )
        if account is None or account.requires_reconnect(
            now=datetime.now(UTC), buffer_hours=buffer_hours
        ):
            raise ReconnectRequiredError(post.id, post.platform)

        # Backfill the publishing account if the post was planned before the
        # owner connected, so the worker can resolve a live token.
        if post.social_account_id is None and account is not None:
            post.social_account_id = account.id

    post.status = "approved"
    # Clear the prior failure so the card reads cleanly while it republishes.
    post.error = None
    # A retry reopens a campaign that already settled as completed, so the worker
    # can run again and check_completion can re-settle it.
    if is_retry and campaign.status == "completed":
        await campaign_service.transition(db, campaign, "publishing", actor_id=actor.id)
    await audit_repo.record(
        db,
        actor_id=actor.id,
        action="post_retried" if is_retry else "post_approved",
        campaign_id=post.campaign_id,
        post_id=post.id,
    )
    return is_retry


async def _apply_ack(db: AsyncSession, post: Post, actor: User) -> None:
    """Validate and mutate one assisted post to ``acknowledged``. No commit."""
    _require_owner(post, actor)
    if post.status != "action_required":
        raise InvalidStateError("Only posts awaiting your action can be marked done.")
    post.status = "acknowledged"
    post.acknowledged_at = datetime.now(UTC)
    await audit_repo.record(
        db,
        actor_id=actor.id,
        action="engagement_acknowledged",
        campaign_id=post.campaign_id,
        post_id=post.id,
    )


async def _apply_skip(db: AsyncSession, post: Post, actor: User) -> None:
    """Validate and mutate one post to ``skipped``. No commit."""
    await _require_owner_admin_or_creator(db, post, actor)
    # Assisted engagement asks (action_required) are skippable too: the person
    # may decide not to comment or like, and that should settle the post. A
    # failed post is skippable so the owner can drop it instead of retrying.
    if post.status not in ("pending", "scheduled", "action_required", "failed"):
        raise InvalidStateError("Only pending or failed posts can be skipped.")
    post.status = "skipped"
    await audit_repo.record(
        db,
        actor_id=actor.id,
        action="post_skipped",
        campaign_id=post.campaign_id,
        post_id=post.id,
    )


async def _load_batch(db: AsyncSession, post_ids: list[uuid.UUID]) -> list[Post]:
    """Load posts for a batch: dedupe, 404 on any missing, one-campaign only."""
    seen: set[uuid.UUID] = set()
    ordered: list[uuid.UUID] = []
    for pid in post_ids:
        if pid not in seen:
            seen.add(pid)
            ordered.append(pid)
    posts: list[Post] = []
    for pid in ordered:
        post = await post_repo.get(db, pid)
        if post is None:
            raise PostNotFoundError(pid)
        posts.append(post)
    if len({p.campaign_id for p in posts}) > 1:
        raise MixedCampaignError()
    return posts


async def approve(
    db: AsyncSession, post_ids: list[uuid.UUID], actor: User
) -> list[Post]:
    """Approve one or more posts atomically, then enqueue publish.

    Open to the owner, an admin, or the campaign creator, so a whole domain
    (every comment, every reshare) can be approved in one batch.
    """
    posts = await _load_batch(db, post_ids)
    for post in posts:
        await _apply_approve(db, post, actor)
    await db.commit()
    # Enqueue only after the commit so the worker never races a not-yet-visible row.
    for post in posts:
        await queue.enqueue_job("publish_post", str(post.id))
    return posts


async def acknowledge(
    db: AsyncSession, post_ids: list[uuid.UUID], actor: User
) -> list[Post]:
    """Mark one or more assisted asks done atomically and settle the campaign."""
    posts = await _load_batch(db, post_ids)
    for post in posts:
        await _apply_ack(db, post, actor)
    if posts:
        await campaign_service.check_completion(db, posts[0].campaign_id)
    await db.commit()
    return posts


async def skip(db: AsyncSession, post_ids: list[uuid.UUID], actor: User) -> list[Post]:
    """Skip one or more posts atomically and settle the campaign."""
    posts = await _load_batch(db, post_ids)
    for post in posts:
        await _apply_skip(db, post, actor)
    if posts:
        await campaign_service.check_completion(db, posts[0].campaign_id)
    await db.commit()
    return posts


async def batch(
    db: AsyncSession, *, op: str, post_ids: list[uuid.UUID], actor: User
) -> list[Post]:
    """Dispatch a batch op (approve, ack, or skip) to the matching handler."""
    if op == "approve":
        return await approve(db, post_ids, actor)
    if op == "ack":
        return await acknowledge(db, post_ids, actor)
    return await skip(db, post_ids, actor)
