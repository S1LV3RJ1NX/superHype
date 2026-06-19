"""Enqueue side of the ARQ queue.

The API uses this to push slow work to the worker and return immediately. Jobs
are referenced by name, so this module does not import the job functions (which
keeps the request path free of worker/DB-pool imports).
"""

from typing import Any

from arq import create_pool
from arq.connections import ArqRedis

from app.core.redis import get_arq_redis_settings

_pool: ArqRedis | None = None


async def get_arq_pool() -> ArqRedis:
    global _pool  # noqa: PLW0603
    if _pool is None:
        _pool = await create_pool(get_arq_redis_settings())
    return _pool


async def enqueue_job(name: str, *args: Any, **kwargs: Any) -> Any:
    """Enqueue a job by function name. Returns the ARQ Job handle."""
    pool = await get_arq_pool()
    return await pool.enqueue_job(name, *args, **kwargs)


async def close_arq_pool() -> None:
    global _pool  # noqa: PLW0603
    if _pool is not None:
        await _pool.aclose()
        _pool = None
