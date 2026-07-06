"""Campaign: an amplify or distribute run and the set of posts it orchestrates.

- amplify: run interactions (like / comment / repost) on an existing post.
- distribute: generate or hand-write M variations, publish them on behalf of
  people, then run interactions across all of them.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Campaign(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "campaigns"
    __table_args__ = (
        Index("ix_campaigns_created_by", "created_by"),
        Index("ix_campaigns_status", "status"),
        # Backs keyset pagination on (created_at, id).
        Index("ix_campaigns_created_at", "created_at"),
        # Backs the due-campaign poll and the events-calendar range query.
        Index("ix_campaigns_scheduled_at", "scheduled_at"),
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
    # Per-campaign generation rules the creator writes; applied on top of the
    # global content rules (unless apply_global_rules is off) during generation.
    custom_rules: Mapped[str | None] = mapped_column(Text)
    apply_global_rules: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    # Shared campaign media, applied to every generated post. image_url is an
    # external URL; image_asset_id points at an uploaded asset (image or video).
    image_url: Mapped[str | None] = mapped_column(Text)
    image_asset_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("assets.id"))
    image_alt: Mapped[str | None] = mapped_column(Text)
    link: Mapped[str | None] = mapped_column(Text)
    link_placement: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="first_comment",
        server_default="first_comment",
    )
    # Author self-comment ("link in the comments"): expanded into a tracked
    # self_comment post row per authored post, placed by the author on their own
    # post after it publishes (assisted-manual until the socialActions API lands).
    self_comment: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="draft", server_default="draft"
    )
    stagger_min_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, default=600, server_default="600"
    )
    stagger_max_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1800, server_default="1800"
    )
    # Optional scheduled auto-launch. When set, the campaign blocks that whole
    # calendar day (company timezone) for everyone else, and a worker poll
    # launches it once the time arrives (if it is ready). Cleared on manual launch
    # and when a schedule is missed.
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    launched_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    launched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
