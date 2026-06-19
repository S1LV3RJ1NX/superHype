"""ARQ job functions: generation, launch, notify, and dependency-aware publish.

Slow and external work runs here, never in a request. Publishing is idempotent
and self-defers when an interaction's target post is not yet live, so the stagger
window and human-paced approvals sequence correctly without a rigid phase lock.
"""

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.safe_fetch import fetch_image
from app.db.session import async_session_factory
from app.logger import get_logger
from app.models.campaign import Campaign
from app.models.post import Post
from app.models.social_account import SocialAccount
from app.providers.linkedin import (
    LinkedInAuthError,
    LinkedInProvider,
    LinkedInRateLimitError,
    linkedin_provider,
)
from app.repositories import audit_repo
from app.repositories.campaign_repo import campaign_repo
from app.repositories.post_repo import post_repo
from app.repositories.social_account_repo import social_account_repo
from app.schemas.post import Assignment
from app.services import campaign_service
from app.services.generation_service import GenerationError
from app.storage import db_asset_store

log = get_logger(__name__)

MAX_RETRIES = 5
_DEPENDENCY_DEFER_SECONDS = 30


def _provider() -> LinkedInProvider:
    """Indirection so tests can monkeypatch the provider."""
    return linkedin_provider


async def generate_drafts(
    ctx: dict, campaign_id: str, assignments: list[dict[str, Any]]
) -> None:
    cid = uuid.UUID(campaign_id)
    parsed = [Assignment.model_validate(a) for a in assignments]
    async with async_session_factory() as db:
        try:
            await campaign_service.build_plan(db, cid, parsed, generate=True)
            await db.commit()
        except GenerationError as exc:
            await db.rollback()
            campaign = await campaign_repo.get(db, cid)
            if campaign is not None and campaign.status == "generating":
                await campaign_service.transition(db, campaign, "failed")
                await audit_repo.record(
                    db,
                    action="campaign_generation_failed",
                    campaign_id=cid,
                    detail={"error": str(exc)[:200]},
                )
                await db.commit()
            log.warning("job.generate_drafts.failed", campaign_id=campaign_id)


async def launch_campaign(ctx: dict, campaign_id: str) -> None:
    import random

    cid = uuid.UUID(campaign_id)
    async with async_session_factory() as db:
        campaign = await campaign_repo.get(db, cid)
        if campaign is None:
            return
        if campaign.status == "review":
            await campaign_service.transition(db, campaign, "publishing")
        posts = await post_repo.list_for_campaign(db, cid)
        await db.commit()

    redis = ctx["redis"]
    for post in posts:
        if post.status != "pending":
            continue
        delay = random.uniform(
            campaign.stagger_min_seconds, campaign.stagger_max_seconds
        )
        await redis.enqueue_job("notify_person", str(post.id), _defer_by=delay)
    await redis.enqueue_job("send_reminders", campaign_id)


async def notify_person(ctx: dict, post_id: str) -> None:
    """Mark the post scheduled and (later) DM the person on Slack to approve."""
    async with async_session_factory() as db:
        post = await post_repo.get(db, uuid.UUID(post_id))
        if post is None or post.status != "pending":
            return
        post.status = "scheduled"
        await db.commit()


async def _resolve_target_urn(db: AsyncSession, post: Post) -> str | None:
    if post.target_post_id is not None:
        target = await post_repo.get(db, post.target_post_id)
        return target.external_id if target else None
    return post.target_external_id


async def _ensure_image_urn(db: AsyncSession, post: Post, acct: SocialAccount) -> None:
    """Upload the post image under its own author once; skip on retry."""
    if post.image_asset_urn is not None:
        return
    if post.image_asset_id is None and not post.image_url:
        return

    if post.image_asset_id is not None:
        data, _ = await db_asset_store.get(db, post.image_asset_id)
    else:
        # External URL is user-controlled: fetch behind the SSRF/size/type guard.
        data, _ = await fetch_image(post.image_url or "")

    urn = await _provider().upload_image(acct, data, alt=post.image_alt)
    post.image_asset_urn = urn
    await db.flush()


async def _dispatch(
    db: AsyncSession,
    post: Post,
    acct: SocialAccount,
    campaign: Campaign,
    target_urn: str | None,
) -> str:
    provider = _provider()
    if post.action == "post":
        return await provider.publish(
            acct,
            post.body or "",
            link=post.link or campaign.link,
            link_in_body=(campaign.link_placement == "body"),
            image_urn=post.image_asset_urn,
        )
    if target_urn is None:
        raise ValueError("Interaction has no resolvable target URN.")
    if post.action == "comment":
        return await provider.comment(acct, target_urn, post.body or "")
    if post.action == "like":
        await provider.like(acct, target_urn)
        return target_urn
    if post.action == "repost_comment":
        return await provider.reshare(acct, target_urn, post.body or "")
    raise ValueError(f"Unknown action: {post.action}")


async def publish_post(ctx: dict, post_id: str) -> None:
    pid = uuid.UUID(post_id)
    async with async_session_factory() as db:
        post = await post_repo.get(db, pid)
        if post is None:
            return
        # Idempotent: a retry never double-posts.
        if post.external_id is not None:
            return
        if post.status in ("skipped", "failed"):
            return

        # Dependency-aware: wait until our target post is live.
        target_urn = await _resolve_target_urn(db, post)
        if (
            post.action != "post"
            and post.target_post_id is not None
            and target_urn is None
        ):
            target = await post_repo.get(db, post.target_post_id)
            # If the target will never publish, stop deferring and fail this row
            # so the campaign can reach a terminal state.
            if target is None or target.status in ("skipped", "failed"):
                await post_repo.mark_failed(db, post, "Target post was not published.")
                await campaign_service.check_completion(db, post.campaign_id)
                await db.commit()
                return
            await ctx["redis"].enqueue_job(
                "publish_post", post_id, _defer_by=_DEPENDENCY_DEFER_SECONDS
            )
            return

        if post.social_account_id is None:
            await post_repo.mark_failed(db, post, "No connected LinkedIn account.")
            await campaign_service.check_completion(db, post.campaign_id)
            await db.commit()
            return

        acct = await social_account_repo.get(db, post.social_account_id)
        campaign = await campaign_repo.get(db, post.campaign_id)
        if acct is None or campaign is None:
            await post_repo.mark_failed(db, post, "Missing account or campaign.")
            await campaign_service.check_completion(db, post.campaign_id)
            await db.commit()
            return

        try:
            await _ensure_image_urn(db, post, acct)
            external_id = await _dispatch(db, post, acct, campaign, target_urn)
            await post_repo.mark_published(db, post, external_id)
            await audit_repo.record(
                db,
                action="post_published",
                campaign_id=post.campaign_id,
                post_id=post.id,
            )
            await campaign_service.check_completion(db, post.campaign_id)
            await db.commit()
        except LinkedInAuthError:
            await social_account_repo.mark_stale(db, post.social_account_id)
            await post_repo.mark_failed(db, post, "LinkedIn token invalid (stale).")
            await campaign_service.check_completion(db, post.campaign_id)
            await db.commit()
            await ctx["redis"].enqueue_job(
                "request_reconnect", str(post.social_account_id)
            )
        except LinkedInRateLimitError as exc:
            await db.rollback()
            await ctx["redis"].enqueue_job(
                "publish_post", post_id, _defer_by=exc.retry_after or 60
            )
        except Exception as exc:
            await db.rollback()
            post = await post_repo.get(db, pid)
            if post is None:
                return
            post.retries += 1
            if post.retries >= MAX_RETRIES:
                await post_repo.mark_failed(db, post, f"Failed: {type(exc).__name__}")
                await campaign_service.check_completion(db, post.campaign_id)
                await db.commit()
            else:
                await db.commit()
                backoff = min(60 * 2**post.retries, 3600)
                await ctx["redis"].enqueue_job(
                    "publish_post", post_id, _defer_by=backoff
                )


async def send_reminders(ctx: dict, campaign_id: str) -> None:
    """Stub until the Slack phase: nudges people with still-pending posts."""
    log.info("job.send_reminders.stub", campaign_id=campaign_id)


async def request_reconnect(ctx: dict, account_id: str) -> None:
    """Stub until the Slack phase: ask the member to reconnect a stale account."""
    log.info("job.request_reconnect.stub", account_id=account_id)
