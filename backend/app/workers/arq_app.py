"""ARQ worker entrypoint.

Run with: uv run arq app.workers.arq_app.WorkerSettings

Registers the job functions and points at Redis. The DB engine and session
factory are module-level singletons (app.db.session), shared across jobs.
"""

from app.core.redis import get_arq_redis_settings
from app.db.session import engine
from app.logger import get_logger
from app.workers.jobs import (
    generate_drafts,
    launch_campaign,
    notify_person,
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
        notify_person,
        publish_post,
        send_reminders,
        request_reconnect,
    ]
    on_startup = on_startup
    on_shutdown = on_shutdown
    redis_settings = get_arq_redis_settings()
    max_tries = 1  # Retries are managed explicitly per job (defer + bounded retries).
