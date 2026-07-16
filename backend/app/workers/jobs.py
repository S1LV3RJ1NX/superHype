"""ARQ job functions: generation, launch, notify, and dependency-aware publish.

Slow and external work runs here, never in a request. Publishing is idempotent
and self-defers when an interaction's target post is not yet live, so the stagger
window and human-paced approvals sequence correctly without a rigid phase lock.
"""

import asyncio
import random
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core import crypto
from app.core.engagement import is_assisted
from app.core.platforms import platform_label
from app.core.safe_fetch import fetch_image, media_kind
from app.core.scheduling import ensure_utc
from app.db.session import async_session_factory
from app.integrations.slack import build_slack_client
from app.logger import get_logger
from app.models.campaign import Campaign
from app.models.post import Post
from app.models.social_account import SocialAccount
from app.providers.base import (
    Provider,
    ProviderAPIError,
    ProviderAuthError,
    ProviderRateLimitError,
)
from app.providers.linkedin import LinkedInAPIError, linkedin_provider
from app.providers.x import x_provider
from app.repositories import audit_repo
from app.repositories.campaign_repo import campaign_repo
from app.repositories.post_repo import post_repo
from app.repositories.social_account_repo import social_account_repo
from app.repositories.user_repo import user_repo
from app.schemas.post import Assignment
from app.services import campaign_service, slack_service
from app.services.engagement_service import engagement_ask
from app.storage import db_asset_store

log = get_logger(__name__)

MAX_RETRIES = 5
_DEPENDENCY_DEFER_SECONDS = 30
# When another worker holds the publish lease, retry this soon rather than drop
# the work: brief so a lost holder (crash) is picked up quickly once its lease
# expires, but long enough not to hot-loop while a healthy holder publishes.
_LEASE_CONTENTION_DEFER_SECONDS = 15


_PROVIDERS: dict[str, Provider] = {
    "linkedin": linkedin_provider,
    "x": x_provider,
}


def _provider(platform: str = "linkedin") -> Provider:
    """Provider for a platform. Indirection so tests can monkeypatch it."""
    return _PROVIDERS.get(platform, linkedin_provider)


async def generate_drafts(
    ctx: dict,
    campaign_id: str,
    assignments: list[dict[str, Any]],
    regenerate: bool = False,
) -> None:
    cid = uuid.UUID(campaign_id)
    parsed = [Assignment.model_validate(a) for a in assignments]
    async with async_session_factory() as db:
        try:
            await campaign_service.build_plan(
                db, cid, parsed, generate=True, regenerate=regenerate
            )
            await db.commit()
        except Exception as exc:
            # Any failure (LLM GenerationError, a DB IntegrityError, anything
            # unexpected) must move the campaign out of "generating"; otherwise it
            # is stuck there forever and the UI polls without end. Roll back the
            # failed unit of work, then flip it to "failed" and audit the reason.
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
            log.warning(
                "job.generate_drafts.failed",
                campaign_id=campaign_id,
                error=str(exc)[:200],
            )


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
    # One bundled ask per participant, not per post: group the campaign's pending
    # posts by owner so each person gets a single Slack card for all their actions.
    # Stagger each participant's notification across the campaign window.
    seen: set[uuid.UUID] = set()
    participant_ids: list[uuid.UUID] = []
    for post in posts:
        if post.status != "pending":
            continue
        if post.user_id not in seen:
            seen.add(post.user_id)
            participant_ids.append(post.user_id)
    # A local override collapses the stagger for fast testing; production leaves it
    # unset and uses the campaign's own window.
    stagger_min = (
        settings.STAGGER_OVERRIDE_MIN_SECONDS
        if settings.STAGGER_OVERRIDE_MIN_SECONDS is not None
        else campaign.stagger_min_seconds
    )
    stagger_max = (
        settings.STAGGER_OVERRIDE_MAX_SECONDS
        if settings.STAGGER_OVERRIDE_MAX_SECONDS is not None
        else campaign.stagger_max_seconds
    )
    stagger_max = max(stagger_min, stagger_max)
    for user_id in participant_ids:
        delay = random.uniform(stagger_min, stagger_max)
        await redis.enqueue_job(
            "notify_participant", campaign_id, str(user_id), _defer_by=delay
        )
    # Deferred nudge: anyone still not approved or not done by then gets re-DMed.
    await redis.enqueue_job(
        "send_reminders",
        campaign_id,
        _defer_by=settings.REMINDER_DELAY_SECONDS,
    )


async def resume_campaign(ctx: dict, campaign_id: str) -> None:
    """Re-drive a resumed campaign's outstanding work.

    Pausing drained the queue (deferred jobs self-aborted), so resuming has to
    re-enqueue: approved posts that were mid-publish get published again
    (publish_post is idempotent), participants still holding pending posts get
    re-notified on a fresh stagger, and everyone still outstanding gets a
    reminder. A no-op if the campaign is no longer publishing.
    """
    cid = uuid.UUID(campaign_id)
    async with async_session_factory() as db:
        campaign = await campaign_repo.get(db, cid)
        if campaign is None or campaign.status != "publishing":
            return
        posts = await post_repo.list_for_campaign(db, cid)

    redis = ctx["redis"]
    # Approved posts were dropped mid-flight by the pause guard; re-publish them.
    for post in posts:
        if post.status == "approved":
            await redis.enqueue_job("publish_post", str(post.id))

    # Participants with still-pending posts were never notified (their staggered
    # notify aborted while paused). Re-notify them on a fresh stagger window.
    seen: set[uuid.UUID] = set()
    pending_participants: list[uuid.UUID] = []
    for post in posts:
        if post.status != "pending":
            continue
        if post.user_id not in seen:
            seen.add(post.user_id)
            pending_participants.append(post.user_id)
    stagger_min = (
        settings.STAGGER_OVERRIDE_MIN_SECONDS
        if settings.STAGGER_OVERRIDE_MIN_SECONDS is not None
        else campaign.stagger_min_seconds
    )
    stagger_max = (
        settings.STAGGER_OVERRIDE_MAX_SECONDS
        if settings.STAGGER_OVERRIDE_MAX_SECONDS is not None
        else campaign.stagger_max_seconds
    )
    stagger_max = max(stagger_min, stagger_max)
    for user_id in pending_participants:
        delay = random.uniform(stagger_min, stagger_max)
        await redis.enqueue_job(
            "notify_participant", campaign_id, str(user_id), _defer_by=delay
        )

    # Nudge everyone still awaiting approval or an assisted action.
    await redis.enqueue_job(
        "send_reminders", campaign_id, _defer_by=settings.REMINDER_DELAY_SECONDS
    )


async def flush_campaign_jobs(ctx: dict, campaign_id: str, post_ids: list[str]) -> None:
    """Drop a reset campaign's still-queued jobs so none fire after a re-launch.

    Enqueued by the reset endpoint so the queue scan stays off the request path.
    The worker guards already no-op these jobs while the campaign sits in review;
    this just clears them out so a later re-launch starts from a clean queue.
    """
    from app.workers.queue import flush_campaign_jobs_on_pool

    await flush_campaign_jobs_on_pool(ctx["redis"], campaign_id, set(post_ids))


async def notify_participant(ctx: dict, campaign_id: str, user_id: str) -> None:
    """Schedule a participant's pending posts and DM them the bundled ask.

    All of one person's pending actions in the campaign move to ``scheduled``
    together, then (if Slack is configured) we send a single card listing every
    action with Approve all / Skip all. The scheduling happens with or without
    Slack, so an unconfigured deployment only drops the DM, never the campaign:
    people still approve from the portal.
    """
    cid = uuid.UUID(campaign_id)
    uid = uuid.UUID(user_id)
    async with async_session_factory() as db:
        # Paused, deleted, or reset before this staggered notify fired: do not
        # schedule the person's posts or DM them. A reset rewinds the campaign to
        # review, so that guard drains jobs left over from the previous run.
        # Resume/relaunch re-drives the fan-out.
        campaign = await campaign_repo.get(db, cid)
        if campaign is None or campaign.status in ("paused", "review"):
            return
        posts = await post_repo.list_for_campaign_user(
            db, cid, uid, statuses=("pending",)
        )
        for post in posts:
            post.status = "scheduled"
        await db.commit()

        if not posts:
            return
        client = build_slack_client()
        if client is None:
            return
        user = await user_repo.get(db, uid)
        if user is None:
            await client.aclose()
            return
        try:
            await slack_service.notify_participant(db, client, campaign, user, posts)
        finally:
            await client.aclose()


async def notify_engagements(ctx: dict, campaign_id: str, user_id: str) -> None:
    """DM a participant their assisted engagements (comment/like) to mark done.

    Fired (deduped, briefly deferred) when an assisted ask goes action_required,
    so a person gets one "mark all done" card for everything currently awaiting
    their hand rather than a DM per ask. A no-op without Slack or if nothing is
    outstanding (the portal carries the same asks either way).
    """
    cid = uuid.UUID(campaign_id)
    uid = uuid.UUID(user_id)
    client = build_slack_client()
    if client is None:
        return
    try:
        async with async_session_factory() as db:
            campaign = await campaign_repo.get(db, cid)
            # Paused, deleted, or reset: skip the engagement nudge. Resume re-DMs
            # via send_reminders; the portal still carries the same asks.
            if campaign is None or campaign.status in ("paused", "review"):
                return
            posts = await post_repo.list_for_campaign_user(
                db, cid, uid, statuses=("action_required",)
            )
            if not posts:
                return
            user = await user_repo.get(db, uid)
            if user is None:
                return
            await slack_service.notify_engagements(db, client, campaign, user, posts)
    finally:
        await client.aclose()


async def handle_slack_interaction(ctx: dict, payload: dict[str, Any]) -> None:
    """Run a signature-verified Slack interaction off the request path.

    The endpoint verifies the signature and acks 200 immediately, then hands the
    parsed payload here so the approval work and the outbound card update happen
    in a job, not inside the request (Slack's own 3s ack window is never at risk).
    A no-op without Slack.
    """
    client = build_slack_client()
    if client is None:
        return
    try:
        async with async_session_factory() as db:
            await slack_service.handle_interaction(db, client, payload)
    finally:
        await client.aclose()


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
        urn = await _provider(post.platform).upload_video(acct, data)
    else:
        urn = await _provider(post.platform).upload_image(
            acct, data, alt=post.image_alt
        )
    post.image_asset_urn = urn
    await db.flush()


# Refresh a token this close to expiry before publishing with it. X access
# tokens live about two hours, so this fires on nearly every X publish; LinkedIn
# accounts usually hold no refresh token and skip it entirely.
_TOKEN_REFRESH_BUFFER_SECONDS = 600
# One approval fans out into several concurrent publish jobs for the same
# account, and X refresh tokens are single-use and rotated, so the refresh
# itself is serialized per account with a Redis lock. Losers wait for the
# winner, then re-read the rotated pair it committed instead of burning the
# same stored refresh token.
_TOKEN_REFRESH_LOCK_TTL_SECONDS = 60
_TOKEN_REFRESH_WAIT_SECONDS = 0.5
_TOKEN_REFRESH_MAX_WAITS = 60


def _token_near_expiry(acct: SocialAccount) -> bool:
    return acct.expires_at is not None and ensure_utc(acct.expires_at) - datetime.now(
        UTC
    ) <= timedelta(seconds=_TOKEN_REFRESH_BUFFER_SECONDS)


async def _ensure_fresh_token(
    db: AsyncSession, acct: SocialAccount, redis: Any
) -> None:
    """Proactively refresh a near-expiry token when a refresh token exists.

    Commits immediately: X rotates the refresh token on every use, so the new
    pair must survive even if the publish attempt afterwards rolls back;
    otherwise the account would be left holding a burned refresh token. Raises
    ProviderAuthError when the refresh token itself is dead, which the caller
    handles like any stale-token failure (mark stale, ask to reconnect).
    """
    if acct.refresh_token_enc is None or acct.expires_at is None:
        return
    if not _token_near_expiry(acct):
        return

    lock_key = f"super-hype:token-refresh:{acct.id}"
    acquired = False
    for _ in range(_TOKEN_REFRESH_MAX_WAITS):
        acquired = bool(
            await redis.set(lock_key, "1", nx=True, ex=_TOKEN_REFRESH_LOCK_TTL_SECONDS)
        )
        if acquired:
            break
        await asyncio.sleep(_TOKEN_REFRESH_WAIT_SECONDS)
    # If the lock never freed, the holder wedged past its TTL; proceed rather
    # than dropping this publish, and let the re-check below limit the damage.
    try:
        # A concurrent job may have rotated the pair while we waited; re-read
        # the row and skip if the token is fresh again.
        await db.refresh(acct)
        if acct.refresh_token_enc is None or not _token_near_expiry(acct):
            return
        data = await _provider(acct.platform).refresh(acct)
        acct.access_token_enc = crypto.encrypt(data["access_token"])
        if data.get("refresh_token"):
            acct.refresh_token_enc = crypto.encrypt(data["refresh_token"])
        if data.get("expires_in"):
            acct.expires_at = datetime.now(UTC) + timedelta(
                seconds=int(data["expires_in"])
            )
        await db.flush()
        await db.commit()
        log.info(
            "publish_post.token_refreshed",
            account_id=str(acct.id),
            platform=acct.platform,
        )
    finally:
        if acquired:
            await redis.delete(lock_key)


async def _dispatch(
    db: AsyncSession,
    post: Post,
    acct: SocialAccount,
    campaign: Campaign,
    target_urn: str | None,
) -> str:
    provider = _provider(post.platform)
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
    if post.action in ("comment", "self_comment"):
        return await provider.comment(acct, target_urn, post.body or "")
    if post.action == "like":
        await provider.like(acct, target_urn)
        return target_urn
    if post.action == "bookmark":
        await provider.bookmark(acct, target_urn)
        return target_urn
    if post.action == "repost_comment":
        return await provider.reshare(acct, target_urn, post.body or "")
    raise ValueError(f"Unknown action: {post.action}")


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
        await _provider(post.platform).delete_post(acct, post.external_id)
    except Exception:
        log.warning("publish_post.rollback_delete_failed", post_id=str(post.id))
    await audit_repo.record(
        db, action="post_rolled_back", campaign_id=post.campaign_id, post_id=post.id
    )


def _forbidden_message(action: str, exc: ProviderAPIError) -> str:
    """Human-readable reason for a 403 so the failure is actionable in the UI.

    On LinkedIn, comments and likes go through the socialActions API, which
    needs the w_member_social_feed scope. That scope is part of the Community
    Management API and is not self-serve; a standard Share-on-LinkedIn app
    (w_member_social) can publish and reshare but cannot comment or like.
    """
    if isinstance(exc, LinkedInAPIError) and action in ("comment", "like"):
        return (
            "Failed: LinkedIn denied this action (403). Comments and likes use the "
            "socialActions API, which requires the w_member_social_feed scope. That "
            "scope is granted only through the Community Management API (not "
            "self-serve). This app currently holds w_member_social, which covers "
            "posts and reshares but not comments or likes. Request Community "
            "Management API access to enable them."
        )
    return f"Failed: the platform denied this action (403). {exc}"[:1000]


def _nonretryable(exc: Exception) -> bool:
    """A provider 4xx is the client's fault (bad target id, missing scope,
    malformed body, duplicate content) and never succeeds on retry, so we fail
    it immediately. 401 and 429 are caught earlier (reconnect and rate-limit
    backoff); 5xx and network blips fall through to the bounded retry."""
    return isinstance(exc, ProviderAPIError) and 400 <= exc.status_code < 500


def _duplicate_urn(exc: Exception) -> str | None:
    """The already-live post id from a duplicate-content rejection, if named.

    LinkedIn's 422 duplicate rejection names the live URN (common after a reset
    and relaunch); the provider extracts it into duplicate_external_id and we
    adopt it so the post is recognized as published rather than failed. X
    rejects duplicates without naming the existing tweet, so those fail with a
    clear message instead.
    """
    if isinstance(exc, ProviderAPIError):
        return exc.duplicate_external_id
    return None


def _publish_failure_message(action: str, exc: Exception, *, rolled_back: bool) -> str:
    """Actionable failure text for the post row, so the UI shows why and the
    owner can fix it and retry."""
    if isinstance(exc, ProviderAPIError) and exc.status_code == 403:
        if rolled_back and isinstance(exc, LinkedInAPIError):
            return (
                "Failed: the post was rolled back because the link could not be "
                "placed in the first comment. Comments require the "
                "w_member_social_feed scope (Community Management API), which this "
                "app does not have. Use body link placement or request the scope."
            )
        if rolled_back:
            return (
                "Failed: the post was rolled back because the link could not be "
                f"placed in the first comment. {exc}"
            )[:1000]
        return _forbidden_message(action, exc)
    # Resharing a feed "activity" URN is rejected: reshareContext.parent must be
    # the original share or ugcPost. This is the usual cause when a campaign was
    # seeded from a /feed/update/urn:li:activity:... URL.
    if (
        isinstance(exc, LinkedInAPIError)
        and exc.status_code == 422
        and "reshareContext" in str(exc)
    ):
        return (
            "Failed: LinkedIn will not reshare this post. The seed link resolved to "
            "a feed activity, but a reshare must target the original share or "
            "ugcPost. Open the post on LinkedIn, use its direct post link (or the "
            "lnkd.in short link), and reseed the campaign with that instead of the "
            "/feed/update/...activity URL."
        )
    return f"Failed: {exc}"[:1000]


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

        # Paused or deleted: drop the job rather than publish. A staggered or
        # backed-off publish enqueued before the pause lands here when it fires;
        # aborting drains the queue. Resume re-enqueues the approved posts. A
        # missing campaign means it was deleted, so there is nothing to do.
        campaign = await campaign_repo.get(db, post.campaign_id)
        # A reset rewinds the campaign to review (and its posts to pending), so a
        # stale publish deferred from the previous run no-ops instead of posting.
        if campaign is None or campaign.status in ("paused", "review"):
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
        if is_assisted(post.action, post.platform) and post.external_id is None:
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
            # Nudge the person on Slack to comment/like and mark it done. A
            # person's asks go action_required at different times (like, then
            # comment, then a self-comment once its post is live), so we dedupe on
            # a per-person job id and defer briefly to bundle them into one card.
            await ctx["redis"].enqueue_job(
                "notify_engagements",
                str(post.campaign_id),
                str(post.user_id),
                _job_id=f"engage:{post.campaign_id}:{post.user_id}",
                _defer_by=settings.ENGAGEMENT_BUNDLE_DELAY_SECONDS,
            )
            return

        if post.social_account_id is None:
            await post_repo.mark_failed(
                db, post, f"No connected {platform_label(post.platform)} account."
            )
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

        # Single-flight lease: claim the post before any provider call so a lost
        # job's recovery (or a second worker replica) can never publish this body
        # or comment concurrently and double-post. If another run holds the lease,
        # re-enqueue shortly rather than dropping the work and let that run finish.
        # The lease is committed so it is immediately visible to other workers.
        if not await post_repo.try_acquire_publish_lease(
            db, pid, now=datetime.now(UTC), ttl_seconds=settings.PUBLISH_LEASE_SECONDS
        ):
            await db.commit()
            await ctx["redis"].enqueue_job(
                "publish_post", post_id, _defer_by=_LEASE_CONTENTION_DEFER_SECONDS
            )
            return
        await db.commit()

        try:
            # Refresh a near-expiry token first (X's ~2h tokens with rotating
            # refresh tokens). Commits its own small unit; a dead refresh token
            # raises ProviderAuthError into the stale-token handler below.
            await _ensure_fresh_token(db, acct, ctx["redis"])

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
                    await campaign_service.check_completion(db, post.campaign_id)
                    await db.commit()
                    return

            # Phase 2: place the link in the first comment (resumable + idempotent).
            if needs_fc and post.first_comment_external_id is None and link:
                fc_urn = await _provider(post.platform).comment(
                    acct, post.external_id or "", link
                )
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
        except ProviderAuthError:
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
            await post_repo.mark_failed(
                db,
                post,
                f"{platform_label(post.platform)} token invalid (stale).",
            )
            await campaign_service.check_completion(db, post.campaign_id)
            await db.commit()
            await ctx["redis"].enqueue_job(
                "request_reconnect", str(post.social_account_id)
            )
        except ProviderRateLimitError as exc:
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
            # Duplicate content: LinkedIn refused because this exact post/reshare
            # is already live, and it names that URN. Adopt it so a reset-and-
            # relaunch settles as published instead of failing something that in
            # fact posted. Only for content actions, and only when the body itself
            # was the duplicate (external_id still None): a 422 duplicate on the
            # first-comment phase must not overwrite the already-live body URN.
            dup_urn = _duplicate_urn(exc)
            if (
                dup_urn is not None
                and post.external_id is None
                and post.action in ("post", "repost_comment")
            ):
                post.external_id = dup_urn
                post.status = "published"
                post.published_at = datetime.now(UTC)
                post.error = None
                await audit_repo.record(
                    db,
                    action="post_published",
                    campaign_id=post.campaign_id,
                    post_id=post.id,
                )
                await campaign_service.check_completion(db, post.campaign_id)
                await db.commit()
                return
            # A 4xx is the client's fault and never succeeds on retry (a 403 scope
            # gap, a 422 bad reshare parent, etc.), so fail it now instead of
            # silently retrying, which leaves the card stuck "processing" for the
            # whole backoff window. 5xx and network blips still get the retry.
            nonretryable = _nonretryable(exc)
            if not nonretryable:
                post.retries += 1
            if nonretryable or post.retries >= MAX_RETRIES:
                # Body live but first comment never landed: roll back for
                # all-or-nothing before marking the post failed.
                rolled_back = (
                    post.external_id is not None
                    and needs_fc
                    and post.first_comment_external_id is None
                )
                if rolled_back:
                    acct = (
                        await social_account_repo.get(db, post.social_account_id)
                        if post.social_account_id is not None
                        else None
                    )
                    if acct is not None:
                        await _rollback_published_post(db, acct, post)
                await post_repo.mark_failed(
                    db,
                    post,
                    _publish_failure_message(post.action, exc, rolled_back=rolled_back),
                )
                await campaign_service.check_completion(db, post.campaign_id)
                await db.commit()
            else:
                await db.commit()
                backoff = min(60 * 2**post.retries, 3600)
                await ctx["redis"].enqueue_job(
                    "publish_post", post_id, _defer_by=backoff
                )
        finally:
            # Always free the lease so the next attempt (a backoff retry here, a
            # later re-approval, or a reconcile re-drive) can re-acquire at once;
            # the TTL is only the crash backstop. Best effort: releasing must not
            # mask the attempt's real outcome. The handlers above leave the session
            # clean (commit or rollback), so this runs in its own small unit.
            try:
                await post_repo.release_publish_lease(db, pid)
                await db.commit()
            except Exception:
                await db.rollback()


async def send_reminders(ctx: dict, campaign_id: str) -> None:
    """Re-DM participants who still have something outstanding in a campaign.

    Two buckets per person: ``scheduled`` posts still awaiting their approval get
    the approve/skip bundle again, and ``action_required`` assisted asks get the
    mark-all-done bundle again. People who are fully settled get nothing. A no-op
    without Slack, since the portal always carries the same outstanding work.
    """
    cid = uuid.UUID(campaign_id)
    client = build_slack_client()
    if client is None:
        return
    try:
        async with async_session_factory() as db:
            campaign = await campaign_repo.get(db, cid)
            # Skip reminders for a deleted, paused, or reset campaign; resume or
            # relaunch re-drives.
            if campaign is None or campaign.status in ("paused", "review"):
                return
            posts = await post_repo.list_for_campaign(db, cid)
            # Bucket outstanding posts per person so each gets at most one DM of
            # each kind, never a card for work that is already settled.
            awaiting_approval: dict[uuid.UUID, list[Post]] = {}
            awaiting_engagement: dict[uuid.UUID, list[Post]] = {}
            for post in posts:
                if post.status == "scheduled":
                    awaiting_approval.setdefault(post.user_id, []).append(post)
                elif post.status == "action_required":
                    awaiting_engagement.setdefault(post.user_id, []).append(post)

            user_ids = set(awaiting_approval) | set(awaiting_engagement)
            for uid in user_ids:
                user = await user_repo.get(db, uid)
                if user is None:
                    continue
                if uid in awaiting_approval:
                    await slack_service.notify_participant(
                        db, client, campaign, user, awaiting_approval[uid]
                    )
                if uid in awaiting_engagement:
                    await slack_service.notify_engagements(
                        db, client, campaign, user, awaiting_engagement[uid]
                    )
    finally:
        await client.aclose()


async def _notify_schedule_missed(campaign: Campaign, reason: str) -> None:
    """Best-effort Slack DM to a campaign's creator that its schedule was missed.

    Runs after the miss is already committed and audited, so a Slack outage never
    blocks freeing the day or processing the rest of the tick.
    """
    if campaign.created_by is None:
        return
    client = build_slack_client()
    if client is None:
        return
    try:
        async with async_session_factory() as db:
            user = await user_repo.get(db, campaign.created_by)
            if user is None:
                return
            await slack_service.notify_schedule_missed(
                db, client, campaign, user, reason
            )
    except Exception as exc:
        log.warning(
            "launch_due_campaigns.notify_failed",
            campaign_id=str(campaign.id),
            error=str(exc)[:200],
        )
    finally:
        await client.aclose()


async def _process_due_campaign(
    ctx: dict, campaign_id: uuid.UUID, now: datetime, grace: timedelta
) -> None:
    """Launch one due campaign, or mark it missed, in its own transaction.

    Due-ness and readiness are re-read inside the transaction so a stale scan
    entry (already launched by a prior tick or another replica) is a no-op. The
    launch stamp is a conditional write that a losing racer skips, so no campaign
    is ever launched twice.
    """
    missed: tuple[Campaign, str] | None = None
    async with async_session_factory() as db:
        campaign = await campaign_repo.get(db, campaign_id)
        if (
            campaign is None
            or campaign.scheduled_at is None
            or campaign.launched_at is not None
        ):
            return

        overdue = now - ensure_utc(campaign.scheduled_at)
        if overdue > grace:
            reason = "grace_exceeded"
        elif campaign.status != "review":
            reason = "not_ready"
        else:
            reason = ""

        if reason:
            # Missed: free the day and audit it. The Slack DM happens after commit.
            campaign.scheduled_at = None
            await audit_repo.record(
                db,
                action="campaign_schedule_missed",
                campaign_id=campaign.id,
                detail={"reason": reason},
            )
            await db.commit()
            missed = (campaign, reason)
        else:
            # Ready and within grace: conditionally stamp the launch. A second tick
            # or replica that already stamped loses the race and returns False.
            won = await campaign_repo.stamp_launched_if_unlaunched(
                db, campaign.id, launched_by=campaign.created_by, now=now
            )
            if not won:
                await db.rollback()
                return
            await audit_repo.record(
                db,
                action="campaign_launched",
                campaign_id=campaign.id,
                detail={"scheduled": True},
            )
            await db.commit()
            # Fixed job id dedupes a re-enqueue after a crash between commit and
            # enqueue (the resweep re-runs this safely while still in review).
            await ctx["redis"].enqueue_job(
                "launch_campaign", str(campaign.id), _job_id=f"launch:{campaign.id}"
            )

    if missed is not None:
        await _notify_schedule_missed(missed[0], missed[1])


async def launch_due_campaigns(ctx: dict) -> None:
    """Cron poll: auto-launch campaigns whose scheduled time has arrived.

    Reads due-ness from Postgres (not Redis-deferred jobs), so a restarted worker
    catches up on everything that came due while it was down. Each campaign is
    processed in isolation, so one bad campaign cannot block the others, and the
    scan is idempotent, so a failed tick simply redoes itself next minute.
    """
    now = datetime.now(UTC)
    grace = timedelta(seconds=settings.SCHEDULE_GRACE_SECONDS)
    async with async_session_factory() as db:
        due = await campaign_repo.find_due_for_launch(db, now)
        # Resweep: stamped-but-still-review campaigns are ones whose launch_campaign
        # enqueue was lost to a crash. Re-enqueue with the same job id (a no-op if
        # it is already queued or running).
        stamped = await campaign_repo.find_stamped_unlaunched(db, now - grace)

    for campaign in due:
        try:
            await _process_due_campaign(ctx, campaign.id, now, grace)
        except Exception as exc:
            log.warning(
                "launch_due_campaigns.campaign_failed",
                campaign_id=str(campaign.id),
                error=str(exc)[:200],
            )

    for campaign in stamped:
        try:
            await ctx["redis"].enqueue_job(
                "launch_campaign", str(campaign.id), _job_id=f"launch:{campaign.id}"
            )
        except Exception as exc:
            log.warning(
                "launch_due_campaigns.reenqueue_failed",
                campaign_id=str(campaign.id),
                error=str(exc)[:200],
            )


# Buffer added to a campaign's stagger window before a still-pending participant
# is treated as a lost notify: the notify is deferred up to stagger_max after
# launch, so we wait a little past that before re-driving.
_NOTIFY_STAGGER_SLACK_SECONDS = 60


def _campaign_stagger_max(campaign: Campaign) -> int:
    """Effective max notify stagger for a campaign (the test override wins)."""
    stagger_min = (
        settings.STAGGER_OVERRIDE_MIN_SECONDS
        if settings.STAGGER_OVERRIDE_MIN_SECONDS is not None
        else campaign.stagger_min_seconds
    )
    stagger_max = (
        settings.STAGGER_OVERRIDE_MAX_SECONDS
        if settings.STAGGER_OVERRIDE_MAX_SECONDS is not None
        else campaign.stagger_max_seconds
    )
    return int(max(stagger_min, stagger_max))


async def _reconcile_one(
    ctx: dict, campaign_id: uuid.UUID, now: datetime, stalled_before: datetime
) -> None:
    """Re-drive one publishing campaign's stuck work, idempotently.

    Read-then-enqueue against durable Postgres state: everything is re-enqueued
    with a fixed job id so repeated ticks dedupe, and every re-driven action is
    idempotent (the publish lease, notify's pending->scheduled move, reminders'
    outstanding-only bucketing) so recovery can never double-act.
    """
    redis = ctx["redis"]
    async with async_session_factory() as db:
        campaign = await campaign_repo.get(db, campaign_id)
        if campaign is None or campaign.status != "publishing":
            return

        # Fully settled but never completed (a crash between the last publish and
        # its inline completion check): settle it now and stop.
        if await post_repo.all_terminal(db, campaign_id):
            await campaign_service.check_completion(db, campaign_id)
            await db.commit()
            return

        posts = await post_repo.list_for_campaign(db, campaign_id)
        launched_at = (
            ensure_utc(campaign.launched_at)
            if campaign.launched_at is not None
            else None
        )
        stagger_max = _campaign_stagger_max(campaign)

    # 1) Stalled approved posts: the publish_post job was lost. Re-enqueue with a
    #    fixed job id (dedupes ticks); the publish lease makes a re-drive safe even
    #    if a deferred job somehow survived.
    for post in posts:
        if post.status == "approved" and ensure_utc(post.updated_at) < stalled_before:
            await redis.enqueue_job(
                "publish_post", str(post.id), _job_id=f"publish:{post.id}"
            )

    # 2) Still-pending posts on a launched campaign past its stagger window: the
    #    participant's staggered notify was lost. Re-notify once per user;
    #    notify_participant is idempotent (pending -> scheduled, DM best effort).
    if launched_at is not None and now >= launched_at + timedelta(
        seconds=stagger_max + _NOTIFY_STAGGER_SLACK_SECONDS
    ):
        pending_users = {post.user_id for post in posts if post.status == "pending"}
        for uid in pending_users:
            await redis.enqueue_job(
                "notify_participant",
                str(campaign_id),
                str(uid),
                _job_id=f"notify:{campaign_id}:{uid}",
            )

    # 3) Lost reminders: outstanding approval/engagement work past the reminder
    #    window. send_reminders is registered with keep_result equal to the
    #    reminder window, so this fixed job id no-ops while a reminder is queued,
    #    running, or ran within the window: at most one nudge per window, not one
    #    per tick.
    outstanding = any(post.status in ("scheduled", "action_required") for post in posts)
    if (
        launched_at is not None
        and outstanding
        and now >= launched_at + timedelta(seconds=settings.REMINDER_DELAY_SECONDS)
    ):
        await redis.enqueue_job(
            "send_reminders", str(campaign_id), _job_id=f"remind:{campaign_id}"
        )


async def reconcile_campaigns(ctx: dict) -> None:
    """Fail-safe cron: recover campaign work lost to a crash or Redis eviction.

    Every deferred job lives only in Redis, so a lost one strands durable state:
    an approved post never publishes, a pending participant is never asked, a
    fully-published campaign hangs in publishing. This reads that stuck state from
    Postgres (the source of truth) and re-drives it idempotently. Each campaign is
    isolated so one bad campaign never blocks the rest, and the scan is idempotent
    so a failed tick simply redoes itself next interval.
    """
    now = datetime.now(UTC)
    stalled_before = now - timedelta(seconds=settings.RECONCILE_STALLED_SECONDS)
    async with async_session_factory() as db:
        campaigns = await campaign_repo.list_by_status(db, "publishing")

    for campaign in campaigns:
        try:
            await _reconcile_one(ctx, campaign.id, now, stalled_before)
        except Exception as exc:
            log.warning(
                "reconcile_campaigns.campaign_failed",
                campaign_id=str(campaign.id),
                error=str(exc)[:200],
            )


async def request_reconnect(ctx: dict, account_id: str) -> None:
    """DM the owner of a stale social account a link to reconnect it.

    Enqueued when publishing hits a 401 and the account is marked stale, so the
    person is nudged out of band instead of only seeing failures in the portal.
    """
    client = build_slack_client()
    if client is None:
        return
    try:
        async with async_session_factory() as db:
            account = await social_account_repo.get(db, uuid.UUID(account_id))
            if account is None:
                return
            user = await user_repo.get(db, account.user_id)
            if user is None:
                return
            await slack_service.notify_reconnect(
                db, client, user, platform=account.platform
            )
    finally:
        await client.aclose()
