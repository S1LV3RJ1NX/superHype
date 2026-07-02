"""Enqueue side of the ARQ queue.

The API uses this to push slow work to the worker and return immediately. Jobs
are referenced by name, so this module does not import the job functions (which
keeps the request path free of worker/DB-pool imports).
"""

from typing import Any

from arq import create_pool
from arq.connections import ArqRedis
from arq.constants import default_queue_name, job_key_prefix
from arq.jobs import Job

from app.core.redis import get_arq_redis_settings

_pool: ArqRedis | None = None

# Jobs whose first positional arg is the campaign id, so they can be matched to a
# campaign directly. publish_post is keyed by post id instead and is matched
# against the campaign's post ids by the caller.
_CAMPAIGN_ARG_JOBS = frozenset(
    {
        "launch_campaign",
        "resume_campaign",
        "notify_participant",
        "notify_engagements",
        "send_reminders",
    }
)


async def get_arq_pool() -> ArqRedis:
    global _pool  # noqa: PLW0603
    if _pool is None:
        _pool = await create_pool(get_arq_redis_settings())
    return _pool


async def enqueue_job(name: str, *args: Any, **kwargs: Any) -> Any:
    """Enqueue a job by function name. Returns the ARQ Job handle."""
    pool = await get_arq_pool()
    return await pool.enqueue_job(name, *args, **kwargs)


async def flush_campaign_jobs_on_pool(
    pool: ArqRedis, campaign_id: str, post_ids: set[str]
) -> int:
    """Drop a campaign's still-queued jobs from the given queue so none fire later.

    The worker guards already no-op jobs for a campaign rewound to review, but a
    reset is meant to be followed by a fresh launch: this removes the leftover
    deferred jobs (staggered notifies, backoff republishes, reminders, engagement
    bundles) so they cannot resurface once the campaign is publishing again.
    Matches campaign-keyed jobs by their campaign id arg and publish_post by post
    id. Returns the number of jobs removed. Best effort: failures are swallowed so
    the caller never fails on queue cleanup.
    """
    try:
        raw_ids = await pool.zrange(default_queue_name, 0, -1)
    except Exception:
        return 0

    removed = 0
    for raw in raw_ids:
        job_id = raw.decode() if isinstance(raw, bytes) else str(raw)
        try:
            info = await Job(job_id, pool).info()
        except Exception:
            continue
        if info is None or not info.args:
            continue
        first = str(info.args[0])
        targets = (
            first in post_ids
            if info.function == "publish_post"
            else info.function in _CAMPAIGN_ARG_JOBS and first == campaign_id
        )
        if not targets:
            continue
        try:
            async with pool.pipeline(transaction=True) as pipe:
                pipe.zrem(default_queue_name, job_id)
                pipe.delete(f"{job_key_prefix}{job_id}")
                await pipe.execute()
            removed += 1
        except Exception:
            continue
    return removed


async def flush_campaign_jobs(campaign_id: str, post_ids: set[str]) -> int:
    """flush_campaign_jobs_on_pool against the shared enqueue pool (best effort)."""
    try:
        pool = await get_arq_pool()
    except Exception:
        return 0
    return await flush_campaign_jobs_on_pool(pool, campaign_id, post_ids)


async def close_arq_pool() -> None:
    global _pool  # noqa: PLW0603
    if _pool is not None:
        await _pool.aclose()
        _pool = None
