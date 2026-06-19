"""Shared async Redis client.

Used for LinkedIn OAuth CSRF state and (later) for the ARQ job queue.
"""

import redis.asyncio as aioredis

from app.config import settings

_pool: aioredis.Redis | None = None


async def get_redis() -> aioredis.Redis:
    """Return a module-level Redis connection, creating it on first call."""
    global _pool  # noqa: PLW0603
    if _pool is None:
        _pool = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    return _pool


async def close_redis() -> None:
    """Shut down the Redis connection pool (called from lifespan)."""
    global _pool  # noqa: PLW0603
    if _pool is not None:
        await _pool.aclose()
        _pool = None
