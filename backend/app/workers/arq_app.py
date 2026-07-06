"""ARQ worker entrypoint.

Run with: uv run arq app.workers.arq_app.WorkerSettings

Registers the job functions and points at Redis. The DB engine and session
factory are module-level singletons (app.db.session), shared across jobs.
"""

from arq import cron, func

from app.config import settings
from app.core.redis import get_arq_redis_settings
from app.db.session import engine
from app.logger import get_logger
from app.workers.jobs import (
    flush_campaign_jobs,
    generate_drafts,
    handle_slack_interaction,
    launch_campaign,
    launch_due_campaigns,
    notify_engagements,
    notify_participant,
    publish_post,
    reconcile_campaigns,
    request_reconnect,
    resume_campaign,
    send_reminders,
)

log = get_logger(__name__)


async def on_startup(ctx: dict) -> None:
    log.info("worker.startup")


async def on_shutdown(ctx: dict) -> None:
    await engine.dispose()
    log.info("worker.shutdown")


class WorkerSettings:
    functions = [
        generate_drafts,
        # No result retention: every launch (manual and scheduled) enqueues with
        # the fixed id launch:{campaign_id} so the resweep dedupes against a
        # queued or running launch, but a kept result would also block a reset
        # and re-launch inside ARQ's default hour. Dedupe only needs to span the
        # job's own lifetime.
        func(launch_campaign, name="launch_campaign", keep_result=0),
        resume_campaign,
        notify_participant,
        # Short keep_result so the per-person job-id dedupe (which coalesces a
        # person's near-simultaneous like/comment into one card) only spans the
        # bundle window, not ARQ's default hour. A later ask (a self-comment once
        # its post is live) can then trigger a fresh card promptly.
        func(
            notify_engagements,
            name="notify_engagements",
            keep_result=settings.ENGAGEMENT_BUNDLE_DELAY_SECONDS,
        ),
        publish_post,
        # Result kept for the whole reminder window: the reconcile cron re-issues
        # reminders with the fixed id remind:{campaign_id}, and the retained
        # result is what throttles that to at most one nudge per window instead
        # of one per cron tick.
        func(
            send_reminders,
            name="send_reminders",
            keep_result=settings.REMINDER_DELAY_SECONDS,
        ),
        request_reconnect,
        handle_slack_interaction,
        flush_campaign_jobs,
        launch_due_campaigns,
        reconcile_campaigns,
    ]
    # Poll every minute for scheduled campaigns whose launch time has arrived.
    # The scan reads due-ness from Postgres and is idempotent, so a missed tick
    # (deploy, restart) is caught up by the next one with no double launch.
    #
    # Reconcile every two minutes: re-drive campaign work (publish, notify,
    # reminders, completion) lost to a worker crash or Redis eviction, read from
    # durable Postgres state. Idempotent and unique, so ticks never pile up and a
    # re-drive never double-acts (the publish lease guarantees no double-post).
    cron_jobs = [
        cron(
            launch_due_campaigns,
            second=0,
            run_at_startup=True,
            unique=True,
        ),
        cron(
            reconcile_campaigns,
            minute=set(range(0, 60, 2)),
            second=30,
            run_at_startup=True,
            unique=True,
        ),
    ]
    on_startup = on_startup
    on_shutdown = on_shutdown
    redis_settings = get_arq_redis_settings()
    max_tries = 1  # Retries are managed explicitly per job (defer + bounded retries).
