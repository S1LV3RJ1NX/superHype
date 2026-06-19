"""Campaign: one announcement and the set of posts generated from it."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Campaign(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "campaigns"
    __table_args__ = (
        Index("ix_campaigns_created_by", "created_by"),
        Index("ix_campaigns_status", "status"),
        # Backs keyset pagination on (created_at, id).
        Index("ix_campaigns_created_at", "created_at"),
    )

    title: Mapped[str] = mapped_column(Text, nullable=False)
    raw_brief: Mapped[str] = mapped_column(Text, nullable=False)
    image_url: Mapped[str | None] = mapped_column(Text)
    image_alt: Mapped[str | None] = mapped_column(Text)
    link: Mapped[str | None] = mapped_column(Text)
    link_placement: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="first_comment",
        server_default="first_comment",
    )
    hero_account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("social_accounts.id")
    )
    writing_skill_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("writing_skills.id")
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="draft", server_default="draft"
    )
    stagger_min_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, default=600, server_default="600"
    )
    stagger_max_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1800, server_default="1800"
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    approved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
