"""ARQ job functions: generation, launch, notify, and dependency-aware publish.

Slow and external work runs here, never in a request. Publishing is idempotent
and self-defers when an interaction's target post is not yet live, so the stagger
window and human-paced approvals sequence correctly without a rigid phase lock.
"""

import random
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.safe_fetch import fetch_image, media_kind
from app.db.session import async_session_factory
from app.logger import get_logger
from app.models.campaign import Campaign
from app.models.post import Post
from app.models.social_account import SocialAccount
from app.providers.linkedin import (
    LinkedInAPIError,
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
from app.services.engagement_service import engagement_ask, is_assisted
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


async def _ensure_media_urn(db: AsyncSession, post: Post, acct: SocialAccount) -> None:
    """Upload the post's media (image or video) under its own author once.

    The media URN must be minted with the post author's token, so this runs per
    post and is skipped on retry (image_asset_urn already set). Uploaded video
    assets go through the Videos API; images and external URLs use the image
    upload path.
    """
    if post.image_asset_urn is not None:
        return
    if post.image_asset_id is None and not post.image_url:
        return

    if post.image_asset_id is not None:
        data, content_type = await db_asset_store.get(db, post.image_asset_id)
    else:
        # External URL is user-controlled: fetch behind the SSRF/size/type guard.
        # Only images are fetched from a URL; video must be an uploaded asset.
        data, content_type = await fetch_image(post.image_url or "")

    if media_kind(content_type) == "video":
        urn = await _provider().upload_video(acct, data)
    else:
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


async def _schedule_self_comment(ctx: dict, post: Post) -> None:
    """Enqueue the author's self-comment on their own post after a random delay.

    The self-comment ("link in the comments") reuses first_comment_external_id as
    its idempotency marker, so it is skipped when a link-in-first-comment already
    claimed that slot. The delay makes it read like a natural follow-up.
    """
    if post.action != "post" or not post.first_comment:
        return
    if post.first_comment_external_id is not None:
        return
    delay = random.uniform(
        settings.SELF_COMMENT_MIN_SECONDS, settings.SELF_COMMENT_MAX_SECONDS
    )
    await ctx["redis"].enqueue_job("place_self_comment", str(post.id), _defer_by=delay)


async def place_self_comment(ctx: dict, post_id: str) -> None:
    """Place the author's own follow-up comment on their published post.

    Idempotent: no-op once first_comment_external_id is set. A stale token marks
    the account stale (the follow-up is best-effort and never rolls back the post);
    a rate limit reschedules; other errors are logged and dropped.
    """
    pid = uuid.UUID(post_id)
    async with async_session_factory() as db:
        post = await post_repo.get(db, pid)
        if post is None or post.action != "post":
            return
        if not post.first_comment or post.first_comment_external_id is not None:
            return
        if post.external_id is None or post.social_account_id is None:
            return
        acct = await social_account_repo.get(db, post.social_account_id)
        if acct is None:
            return
        try:
            fc_urn = await _provider().comment(
                acct, post.external_id, post.first_comment
            )
        except LinkedInAuthError:
            await social_account_repo.mark_stale(db, post.social_account_id)
            await db.commit()
            await ctx["redis"].enqueue_job(
                "request_reconnect", str(post.social_account_id)
            )
            return
        except LinkedInRateLimitError as exc:
            await ctx["redis"].enqueue_job(
                "place_self_comment", post_id, _defer_by=exc.retry_after or 60
            )
            return
        except Exception as exc:
            log.warning(
                "place_self_comment.failed",
                post_id=post_id,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return
        post.first_comment_external_id = fc_urn
        await audit_repo.record(
            db,
            action="self_comment_placed",
            campaign_id=post.campaign_id,
            post_id=post.id,
        )
        await db.commit()


async def _guardrail_defer(db: AsyncSession, account_id: uuid.UUID) -> float | None:
    """Return seconds to defer if this account would breach an authenticity guard.

    Two guards keep a coordinated push reading as authentic rather than as a pod:
    a minimum spacing between an account's actions, and a daily action cap. When a
    guard trips we defer (overflow rolls into the next day's window) rather than
    skip, so the action still happens. Returns None when it is safe to proceed.
    """
    now = datetime.now(UTC)
    since = now - timedelta(hours=24)
    times = await post_repo.published_times_for_account(db, account_id, since)
    if not times:
        return None

    elapsed = (now - max(times)).total_seconds()
    min_gap = settings.MIN_SECONDS_BETWEEN_ACCOUNT_ACTIONS
    if elapsed < min_gap:
        return min_gap - elapsed

    cap = settings.MAX_ACTIONS_PER_ACCOUNT_PER_DAY
    if len(times) >= cap:
        # Defer until the oldest of the most recent `cap` actions ages out of the
        # trailing 24h window; self-resolving, so this never loops forever.
        oldest_relevant = sorted(times)[-cap]
        defer_by = (oldest_relevant + timedelta(hours=24) - now).total_seconds()
        return max(defer_by, 60.0)

    return None


async def _rollback_published_post(
    db: AsyncSession, acct: SocialAccount, post: Post
) -> None:
    """Best-effort delete a live post when its first comment cannot be placed.

    Honors the all-or-nothing rule for link-in-first-comment: if the body is live
    but the link comment never lands, we remove the post rather than leave it up
    without the link. The delete itself is best-effort (it may fail on a stale
    token); failures are logged, not raised.
    """
    if post.external_id is None:
        return
    try:
        await _provider().delete_post(acct, post.external_id)
    except Exception:
        log.warning("publish_post.rollback_delete_failed", post_id=str(post.id))
    await audit_repo.record(
        db, action="post_rolled_back", campaign_id=post.campaign_id, post_id=post.id
    )


def _forbidden_message(action: str, exc: LinkedInAPIError) -> str:
    """Human-readable reason for a 403 so the failure is actionable in the UI.

    Comments and likes go through the socialActions API, which needs the
    w_member_social_feed scope. That scope is part of the Community Management
    API and is not self-serve; a standard Share-on-LinkedIn app (w_member_social)
    can publish and reshare but cannot comment or like.
    """
    if action in ("comment", "like"):
        return (
            "Failed: LinkedIn denied this action (403). Comments and likes use the "
            "socialActions API, which requires the w_member_social_feed scope. That "
            "scope is granted only through the Community Management API (not "
            "self-serve). This app currently holds w_member_social, which covers "
            "posts and reshares but not comments or likes. Request Community "
            "Management API access to enable them."
        )
    return f"Failed: LinkedIn denied this action (403). {exc}"[:1000]


async def publish_post(ctx: dict, post_id: str) -> None:
    pid = uuid.UUID(post_id)
    async with async_session_factory() as db:
        post = await post_repo.get(db, pid)
        if post is None:
            return
        # Terminal or already-asked states are no-ops: skipped/failed are done,
        # action_required/acknowledged mean the assisted ask was already raised.
        if post.status in ("skipped", "failed", "action_required", "acknowledged"):
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

        # Assisted-manual engagement: hand the comment or like to the person
        # rather than calling the API. The target is now live, so build the deep
        # link, raise the ask, and stop before any provider call or token check.
        # external_id is None guards against re-processing a row that somehow
        # already published (e.g. data from when the flag was on).
        if is_assisted(post.action) and post.external_id is None:
            if target_urn is None:
                await post_repo.mark_failed(
                    db, post, "Interaction has no resolvable target."
                )
                await campaign_service.check_completion(db, post.campaign_id)
                await db.commit()
                return
            ask = engagement_ask(post, target_urn)
            post.status = "action_required"
            post.engagement_url = ask.target_url
            await db.flush()
            await audit_repo.record(
                db,
                action="engagement_requested",
                campaign_id=post.campaign_id,
                post_id=post.id,
            )
            await campaign_service.check_completion(db, post.campaign_id)
            await db.commit()
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

        link = post.link or campaign.link
        needs_fc = (
            post.action == "post"
            and campaign.link_placement == "first_comment"
            and bool(link)
        )

        # Idempotent: no-op only when the post is fully done. For a first-comment
        # post that means the body is live AND the link comment is placed; a retry
        # in between resumes at the comment rather than re-publishing the body.
        if post.external_id is not None and (
            not needs_fc or post.first_comment_external_id is not None
        ):
            # Resume-safe: if the body committed but the self-comment enqueue was
            # lost (crash between commit and enqueue), any later publish_post run
            # re-schedules it. _schedule_self_comment is a no-op once it is placed
            # or when a link already claimed the first-comment slot.
            await _schedule_self_comment(ctx, post)
            return

        # Authenticity guardrails: only gate the outbound action itself (when the
        # body is not yet live), never the first-comment resume.
        if post.external_id is None:
            defer_by = await _guardrail_defer(db, post.social_account_id)
            if defer_by is not None:
                await ctx["redis"].enqueue_job(
                    "publish_post", post_id, _defer_by=defer_by
                )
                return

        try:
            # Phase 1: publish the body. external_id is committed before we touch
            # the first comment, so a later failure can never re-publish it.
            if post.external_id is None:
                await _ensure_media_urn(db, post, acct)
                external_id = await _dispatch(db, post, acct, campaign, target_urn)
                post.external_id = external_id
                post.published_at = datetime.now(UTC)
                if not needs_fc:
                    post.status = "published"
                await db.flush()
                await audit_repo.record(
                    db,
                    action="post_published",
                    campaign_id=post.campaign_id,
                    post_id=post.id,
                )
                await db.commit()
                if not needs_fc:
                    await _schedule_self_comment(ctx, post)
                    await campaign_service.check_completion(db, post.campaign_id)
                    await db.commit()
                    return

            # Phase 2: place the link in the first comment (resumable + idempotent).
            if needs_fc and post.first_comment_external_id is None and link:
                fc_urn = await _provider().comment(acct, post.external_id or "", link)
                post.first_comment_external_id = fc_urn
                await audit_repo.record(
                    db,
                    action="first_comment_placed",
                    campaign_id=post.campaign_id,
                    post_id=post.id,
                )
            await post_repo.mark_published(db, post, post.external_id or "")
            await campaign_service.check_completion(db, post.campaign_id)
            await db.commit()
        except LinkedInAuthError:
            await db.rollback()
            post = await post_repo.get(db, pid)
            if post is None or post.social_account_id is None:
                return
            acct = await social_account_repo.get(db, post.social_account_id)
            # If the body went live but the comment could not (token went stale),
            # try to roll it back so we do not leave a post without its link.
            if acct is not None and post.external_id is not None and needs_fc:
                await _rollback_published_post(db, acct, post)
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
            # Surface the real reason (LinkedInAPIError carries the status code and
            # response body) so failures are debuggable from logs and the post row.
            log.warning(
                "publish_post.attempt_failed",
                post_id=post_id,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            post = await post_repo.get(db, pid)
            if post is None:
                return
            # A 403 is a permissions problem (typically a missing scope, e.g.
            # comments/likes need w_member_social_feed). Retrying never helps, so
            # fail immediately with an actionable message.
            if isinstance(exc, LinkedInAPIError) and exc.status_code == 403:
                # If the body is already live and only the link-in-first-comment
                # failed (the first comment also needs w_member_social_feed), roll
                # the post back so we honor all-or-nothing instead of leaving a
                # live post recorded as failed.
                if post.external_id is not None and (
                    needs_fc and post.first_comment_external_id is None
                ):
                    acct = (
                        await social_account_repo.get(db, post.social_account_id)
                        if post.social_account_id is not None
                        else None
                    )
                    if acct is not None:
                        await _rollback_published_post(db, acct, post)
                    msg = (
                        "Failed: the post was rolled back because the link could not "
                        "be placed in the first comment. Comments require the "
                        "w_member_social_feed scope (Community Management API), which "
                        "this app does not have. Use body link placement or request "
                        "the scope."
                    )
                else:
                    msg = _forbidden_message(post.action, exc)
                await post_repo.mark_failed(db, post, msg)
                await campaign_service.check_completion(db, post.campaign_id)
                await db.commit()
                return
            post.retries += 1
            if post.retries >= MAX_RETRIES:
                # Body live but first comment never landed: roll back for
                # all-or-nothing before marking the post failed.
                if post.external_id is not None and (
                    needs_fc and post.first_comment_external_id is None
                ):
                    acct = (
                        await social_account_repo.get(db, post.social_account_id)
                        if post.social_account_id is not None
                        else None
                    )
                    if acct is not None:
                        await _rollback_published_post(db, acct, post)
                await post_repo.mark_failed(db, post, f"Failed: {exc}"[:1000])
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
