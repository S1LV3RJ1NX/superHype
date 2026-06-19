"""Application settings, loaded from the environment via pydantic-settings.

Every value comes from the environment (or backend/.env in local dev). For Phase 0
the auth, LinkedIn, generation, and Slack settings are optional so the app boots
without them; later phases tighten the ones they need.
"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Core infrastructure (set in backend/.env).
    DATABASE_URL: str = (
        "postgresql+asyncpg://postgres:postgres@localhost:5432/super-hype"
    )
    REDIS_URL: str = "redis://localhost:6379/0"
    DATABASE_POOL_SIZE: int = 20
    DATABASE_MAX_OVERFLOW: int = 10

    # Public URLs.
    APP_URL: str = "http://localhost:8000"
    FRONTEND_URL: str = "http://localhost:5173"
    # Deployment environment. Defaults to production so anything that forgets to
    # set it is treated as locked down (docs disabled); local dev sets ENV=local.
    ENV: str = "production"

    # Security.
    JWT_SECRET: str = "change-me-in-env"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 720
    TOKEN_ENCRYPTION_KEY: str | None = None
    OAUTHLIB_INSECURE_TRANSPORT: bool = False

    # Auth and access control.
    COMPANY_EMAIL_DOMAIN: str = "example.com"
    BOOTSTRAP_ADMIN_EMAILS: str = ""

    # Google OAuth.
    GOOGLE_CLIENT_ID: str | None = None
    GOOGLE_CLIENT_SECRET: str | None = None

    # LinkedIn.
    LINKEDIN_CLIENT_ID: str | None = None
    LINKEDIN_CLIENT_SECRET: str | None = None
    LINKEDIN_API_VERSION: str = "202606"

    # LLM gateway (OpenAI-compatible).
    LLM_GATEWAY_URL: str | None = None
    LLM_API_KEY: str | None = None
    LLM_MODEL_NAME: str | None = None

    # Slack.
    SLACK_BOT_TOKEN: str | None = None
    SLACK_SIGNING_SECRET: str | None = None

    # Observability.
    SENTRY_DSN: str | None = None

    CORS_ORIGINS: str = Field(default="http://localhost:5173")

    @property
    def is_production(self) -> bool:
        return self.ENV.lower() in {"production", "prod"}

    @property
    def bootstrap_admin_emails(self) -> list[str]:
        return [
            email.strip().lower()
            for email in self.BOOTSTRAP_ADMIN_EMAILS.split(",")
            if email.strip()
        ]

    @property
    def cors_origins(self) -> list[str]:
        return [
            origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()
        ]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
