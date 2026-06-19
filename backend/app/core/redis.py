"""Shared async Redis client.

Used for LinkedIn OAuth CSRF state and for the ARQ job queue.
"""

import redis.asyncio as aioredis
from arq.connections import RedisSettings

from app.config import settings


def get_arq_redis_settings() -> RedisSettings:
    """Parse REDIS_URL into ARQ RedisSettings for the worker and the enqueue pool."""
    return RedisSettings.from_dsn(settings.REDIS_URL)


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
