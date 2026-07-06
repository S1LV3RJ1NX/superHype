"""Application settings, loaded from the environment via pydantic-settings.

Every value comes from the environment (or backend/.env in local dev). Core infra,
auth, LinkedIn, and LLM gateway settings are required; Slack and observability are
optional.
"""

from functools import lru_cache
from zoneinfo import ZoneInfo

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

    # Local testing override for the per-campaign notification stagger. When set,
    # launch uses this window instead of the campaign's own stagger_min/max, so a
    # developer can get the Slack DM (and scheduled posts) almost immediately
    # instead of waiting out the 10-30 minute production default. Leave unset in
    # production; the per-campaign values are the real control there.
    STAGGER_OVERRIDE_MIN_SECONDS: int | None = None
    STAGGER_OVERRIDE_MAX_SECONDS: int | None = None

    # A person's assisted engagements (comment, like, self-comment) become
    # actionable at different times as their targets publish. This short window
    # lets the worker coalesce them into one Slack "mark all done" card instead of
    # firing a separate DM per ask. Also the job-id dedupe window for that bundle.
    ENGAGEMENT_BUNDLE_DELAY_SECONDS: int = 30

    # How long after launch to re-DM anyone who still has posts awaiting their
    # approval or an assisted engagement they have not marked done. Defaults to a
    # few hours; drop it for a quick local check of the reminder path.
    REMINDER_DELAY_SECONDS: int = 6 * 60 * 60

    # Fail-safe reconciliation. A worker holds the single-flight publish lease for
    # this long before it expires; it must exceed the slowest publish call (media
    # upload + post + first comment) so a healthy job never loses its own lease,
    # while still freeing a crashed job's lease reasonably fast.
    PUBLISH_LEASE_SECONDS: int = 600
    # An approved post whose row has not changed in this long is treated as a lost
    # publish job and re-driven by the reconcile poll. Longer than the largest
    # publish backoff (60 * 2**4 = 960s), so reconcile never pre-empts a retry
    # that is still legitimately scheduled; the lease would make that race safe,
    # but pre-empting would consume the final retry early.
    RECONCILE_STALLED_SECONDS: int = 1200

    # Scheduled auto-launch. Company timezone that defines a scheduling "day", so
    # the one-campaign-per-day rule and the events calendar align with the team's
    # local calendar rather than UTC.
    SCHEDULE_TIMEZONE: str = "Asia/Kolkata"
    # How far past its scheduled time a campaign may still auto-launch on
    # catch-up (covers deploys and short worker outages). Anything overdue by more
    # than this is not launched at the wrong time; it is treated as missed and the
    # creator is nudged to reschedule.
    SCHEDULE_GRACE_SECONDS: int = 60 * 60

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
    BRAND_KEYWORDS: str

    # Distribute cross-engagement: each member likes and comments on at most this
    # many other members' posts, so a large campaign cannot fan out quadratically.
    # Posts authored by a founder team (below) are chosen first.
    DISTRIBUTE_MAX_ENGAGEMENT_TARGETS: int = 10

    # Team names whose members count as founders for engagement prioritization.
    # Comma-separated, matched case-insensitively against the team name.
    FOUNDER_TEAM_NAMES: str = "Founders"

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

    @property
    def founder_team_names(self) -> set[str]:
        return {
            name.strip().lower()
            for name in self.FOUNDER_TEAM_NAMES.split(",")
            if name.strip()
        }

    @property
    def schedule_tz(self) -> ZoneInfo:
        """Company timezone used for the scheduling day boundary."""
        return ZoneInfo(self.SCHEDULE_TIMEZONE)


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


settings = get_settings()
