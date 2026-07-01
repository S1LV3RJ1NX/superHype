"""Clear the ARQ worker queue in Redis.

Run with: uv run python -m scripts.flush_queue

Deletes only the ``arq:*`` keys (the deferred/pending job zset, job payloads,
results, and the health check) on the configured Redis DB, so it is safe to run
against a shared Redis without touching OAuth state or other app data. The
running worker simply recreates its health-check key afterwards.
"""

import asyncio

from redis.asyncio import from_url

from app.config import settings


async def flush() -> None:
    r = from_url(settings.REDIS_URL)
    try:
        keys = [key async for key in r.scan_iter(match="arq:*")]
        deleted = await r.delete(*keys) if keys else 0
        print(f"Flushed {deleted} arq keys from the worker queue.")
    finally:
        await r.aclose()


if __name__ == "__main__":
    asyncio.run(flush())
