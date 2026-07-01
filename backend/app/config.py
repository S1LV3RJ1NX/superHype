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
    # App session lifetime. 7 days by default for an internal tool, so people are
    # not pushed back through Google login during a normal work week. There is no
    # refresh token; when this expires the next request 401s and the SPA re-logs in.
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 10080
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
    # Comments and likes go through the socialActions API, which needs the
    # w_member_social_feed scope, granted only through the Community Management
    # API (not self-serve). Until that access lands this stays off and comments
    # and likes become a guided human action (assisted-manual): we resolve the
    # target, deep-link the person to it, and they act in their own browser.
    # Posts and reshares stay fully automated either way. Flip to true the day
    # Community Management access is approved to dispatch comments and likes
    # through the API; no code change is needed.
    COMMUNITY_MANAGEMENT_ENABLED: bool = False

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

    # Uploaded campaign video cap. Short clips only; bytes still live in the DB
    # asset store for now, so keep this modest until object storage lands.
    MAX_VIDEO_BYTES: int = 64 * 1024 * 1024

    # A post's self-comment ("link in the comments") is placed by the author on
    # their own post after a random delay in this window, so it reads like a
    # natural follow-up rather than an instant bot reply.
    SELF_COMMENT_MIN_SECONDS: int = 300
    SELF_COMMENT_MAX_SECONDS: int = 3600

    # Leaderboard: a direct post whose text mentions one of these keywords earns
    # the brand bonus (case-insensitive substring match). Comma-separated.
    BRAND_KEYWORDS: str = "TrueFoundry,TFY,true foundry"

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

    @property
    def brand_keywords(self) -> list[str]:
        return [
            kw.strip().lower() for kw in self.BRAND_KEYWORDS.split(",") if kw.strip()
        ]


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


settings = get_settings()
