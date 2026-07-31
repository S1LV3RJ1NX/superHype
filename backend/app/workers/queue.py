"""Enqueue side of the ARQ queue.

The API uses this to push slow work to the worker and return immediately. Jobs
are referenced by name, so this module does not import the job functions (which
keeps the request path free of worker/DB-pool imports).
"""

from collections.abc import Callable
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


async def _flush_matching(
    pool: ArqRedis, matches: Callable[[str, tuple[Any, ...]], bool]
) -> int:
    """Drop every still-queued job the predicate claims. Best effort.

    Failures are swallowed so callers never fail on queue cleanup, and jobs
    already picked up by a worker are simply not in the zset to begin with.
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
        if not matches(info.function, tuple(info.args)):
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


async def flush_campaign_jobs_on_pool(
    pool: ArqRedis, campaign_id: str, post_ids: set[str]
) -> int:
    """Drop a campaign's still-queued jobs from the given queue so none fire later.

    The worker guards already no-op jobs for a campaign rewound to review, but a
    reset is meant to be followed by a fresh launch: this removes the leftover
    deferred jobs (staggered notifies, backoff republishes, reminders, engagement
    bundles) so they cannot resurface once the campaign is publishing again.
    Matches campaign-keyed jobs by their campaign id arg and publish_post by post
    id. Returns the number of jobs removed.
    """

    def _matches(function: str, args: tuple[Any, ...]) -> bool:
        first = str(args[0])
        if function == "publish_post":
            return first in post_ids
        return function in _CAMPAIGN_ARG_JOBS and first == campaign_id

    return await _flush_matching(pool, _matches)


async def flush_member_jobs_on_pool(
    pool: ArqRedis,
    *,
    post_ids: set[str],
    user_ids: set[str],
    account_ids: set[str],
) -> int:
    """Drop still-queued jobs belonging to people who are about to be deleted.

    Their posts go with them, so a deferred publish or reminder would wake up
    pointing at rows that no longer exist. Per-member jobs are keyed three ways:
    publish_post by post id, the notify jobs by user id in their second arg, and
    request_reconnect by social account id.
    """

    def _matches(function: str, args: tuple[Any, ...]) -> bool:
        if function == "publish_post":
            return str(args[0]) in post_ids
        if function == "request_reconnect":
            return str(args[0]) in account_ids
        if function in ("notify_participant", "notify_engagements"):
            return len(args) > 1 and str(args[1]) in user_ids
        return False

    return await _flush_matching(pool, _matches)


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
