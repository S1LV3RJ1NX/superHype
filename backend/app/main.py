"""FastAPI application factory: logging, CORS, and router registration."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.logger import configure_logging, get_logger
from app.views import api_router
from app.views.health import router as health_router


def create_app() -> FastAPI:
    configure_logging()
    log = get_logger(__name__)

    app = FastAPI(title="super-hype", version="0.1.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health_router)
    app.include_router(api_router)

    log.info("app.startup", environment=settings.ENVIRONMENT)
    return app


app = create_app()
