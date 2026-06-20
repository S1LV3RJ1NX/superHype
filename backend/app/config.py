"""Application settings, loaded from the environment via pydantic-settings.

Every value comes from the environment (or backend/.env in local dev). Core infra,
auth, LinkedIn, and LLM gateway settings are required; Slack and observability are
optional.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Core infrastructure (set in backend/.env).
    DATABASE_URL: str
    REDIS_URL: str
    DATABASE_POOL_SIZE: int = 20
    DATABASE_MAX_OVERFLOW: int = 10

    # Public URLs.
    APP_URL: str
    FRONTEND_URL: str
    CORS_ORIGINS: str
    # Deployment environment. Defaults to production so anything that forgets to
    # set it is treated as locked down (docs disabled); local dev sets ENV=local.
    ENV: str = "production"

    # Security.
    JWT_SECRET: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 720
    TOKEN_ENCRYPTION_KEY: str
    OAUTHLIB_INSECURE_TRANSPORT: bool = False

    # Auth and access control.
    COMPANY_EMAIL_DOMAIN: str
    BOOTSTRAP_ADMIN_EMAILS: str

    # Google OAuth.
    GOOGLE_CLIENT_ID: str
    GOOGLE_CLIENT_SECRET: str

    # LinkedIn.
    LINKEDIN_CLIENT_ID: str
    LINKEDIN_CLIENT_SECRET: str
    LINKEDIN_API_VERSION: str = "202606"
    # Re-consent is required once a token is stale, expired, or within this many
    # hours of expiry, so an action is never approved against a dying token.
    LINKEDIN_RECONNECT_BUFFER_HOURS: int = 24

    # LLM gateway (OpenAI-compatible).
    LLM_GATEWAY_URL: str
    LLM_API_KEY: str
    LLM_MODEL_NAME: str
    # Comment-quality floor: generated interactions shorter than this (in words)
    # are rejected and regenerated, so we never publish pod-like one-liners.
    MIN_COMMENT_WORDS: int = 12

    # Authenticity guardrails for publishing. Keep a person's account from acting
    # too often or too fast, which is what LinkedIn's pod detection flags.
    MAX_ACTIONS_PER_ACCOUNT_PER_DAY: int = 10
    MIN_SECONDS_BETWEEN_ACCOUNT_ACTIONS: int = 90

    # Slack.
    SLACK_BOT_TOKEN: str | None = None
    SLACK_SIGNING_SECRET: str | None = None

    # Observability.
    SENTRY_DSN: str | None = None

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
    return Settings()  # type: ignore[call-arg]


settings = get_settings()
