"""Campaign: an amplify or distribute run and the set of posts it orchestrates.

- amplify: run interactions (like / comment / repost) on an existing post.
- distribute: generate or hand-write M variations, publish them on behalf of
  people, then run interactions across all of them.
"""

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
    # amplify | distribute
    type: Mapped[str] = mapped_column(
        String(16), nullable=False, default="amplify", server_default="amplify"
    )
    # Optional internal notes / brief about the campaign.
    raw_brief: Mapped[str | None] = mapped_column(Text)

    # Seed of the campaign: the target post for amplify, the basis for variations
    # in distribute. Either a pasted URL (we parse the activity URN into seed_urn)
    # and/or the raw post text used as generation context.
    seed_url: Mapped[str | None] = mapped_column(Text)
    seed_urn: Mapped[str | None] = mapped_column(Text)
    seed_content: Mapped[str | None] = mapped_column(Text)

    # Lightweight generation hints (replace the retired writing-skill profile).
    tone: Mapped[str | None] = mapped_column(Text)
    length: Mapped[str | None] = mapped_column(String(32))
    language: Mapped[str] = mapped_column(
        String(16), nullable=False, default="en", server_default="en"
    )
    extra_instructions: Mapped[str | None] = mapped_column(Text)

    # Shared campaign image defaults (a variation may override per post).
    image_url: Mapped[str | None] = mapped_column(Text)
    image_alt: Mapped[str | None] = mapped_column(Text)
    link: Mapped[str | None] = mapped_column(Text)
    link_placement: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="first_comment",
        server_default="first_comment",
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
    launched_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    launched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
