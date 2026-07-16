"""SocialAccount: a user's connected LinkedIn identity with encrypted tokens."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPrimaryKeyMixin


class SocialAccount(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "social_accounts"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "platform", name="uq_social_accounts_user_platform"
        ),
        Index("ix_social_accounts_status", "status"),
        Index("ix_social_accounts_expires_at", "expires_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    platform: Mapped[str] = mapped_column(
        String(32), nullable=False, default="linkedin", server_default="linkedin"
    )
    external_urn: Mapped[str | None] = mapped_column(Text)
    display_name: Mapped[str | None] = mapped_column(Text)
    access_token_enc: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    refresh_token_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    scopes: Mapped[list[str] | None] = mapped_column(
        ARRAY(Text).with_variant(JSON(), "sqlite")
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active", server_default="active"
    )
    connected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    def requires_reconnect(self, *, now: datetime, buffer_hours: int) -> bool:
        """True if this account cannot safely publish without re-consent.

        Standard Share-on-LinkedIn apps get no refresh token, so an expired or
        soon-to-expire access token (or one already marked stale) can only be
        fixed by the member re-consenting. An account holding a refresh token
        (X with offline.access) is refreshed by the worker itself, so expiry
        alone never forces re-consent there; only a dead refresh token (the
        account marked stale on a 401) does.
        """
        if self.status != "active":
            return True
        if self.refresh_token_enc is not None:
            return False
        if self.expires_at is None:
            return True
        expires_at = self.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        return expires_at <= now + timedelta(hours=buffer_hours)
