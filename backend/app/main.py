"""FastAPI application factory: logging, startup health checks, CORS, routers."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.config import settings
from app.db.session import engine
from app.logger import configure_logging, get_logger

log = get_logger(__name__)


async def _check_database() -> None:
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))


async def _check_redis() -> None:
    client = aioredis.from_url(
        settings.REDIS_URL,
        socket_connect_timeout=10,
        socket_timeout=10,
    )
    try:
        await client.ping()
    finally:
        await client.aclose()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
    """Verify Postgres and Redis are reachable before serving.

    If either is down, log a clear error and abort startup so the process exits
    instead of accepting traffic it cannot serve.
    """
    try:
        await _check_database()
    except Exception as exc:
        detail = str(exc) or repr(exc)
        log.error("startup.database_unreachable", error=detail)
        raise RuntimeError(
            f"Database is unreachable at startup: {detail}. Check DATABASE_URL."
        ) from exc

    try:
        await _check_redis()
    except Exception as exc:
        detail = str(exc) or repr(exc)
        log.error("startup.redis_unreachable", error=detail)
        raise RuntimeError(
            f"Redis is unreachable at startup: {detail}. Check REDIS_URL."
        ) from exc

    log.info("startup.checks_passed", env=settings.ENV)
    yield
    await engine.dispose()


def create_app() -> FastAPI:
    configure_logging()

    from app.views import api_router
    from app.views.health import router as health_router

    # Interactive docs are open in local/dev but disabled in production.
    docs_enabled = not settings.is_production
    app = FastAPI(
        title="super-hype",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
        openapi_url="/openapi.json" if docs_enabled else None,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health_router)
    app.include_router(api_router)
    return app


app = create_app()
