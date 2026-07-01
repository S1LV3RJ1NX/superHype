"""ARQ worker entrypoint.

Run with: uv run arq app.workers.arq_app.WorkerSettings

Registers the job functions and points at Redis. The DB engine and session
factory are module-level singletons (app.db.session), shared across jobs.
"""

from arq import func

from app.config import settings
from app.core.redis import get_arq_redis_settings
from app.db.session import engine
from app.logger import get_logger
from app.workers.jobs import (
    generate_drafts,
    handle_slack_interaction,
    launch_campaign,
    notify_engagements,
    notify_participant,
    publish_post,
    request_reconnect,
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
        launch_campaign,
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
        send_reminders,
        request_reconnect,
        handle_slack_interaction,
    ]
    on_startup = on_startup
    on_shutdown = on_shutdown
    redis_settings = get_arq_redis_settings()
    max_tries = 1  # Retries are managed explicitly per job (defer + bounded retries).
