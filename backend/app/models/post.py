"""Post: one action for one person on one platform, with a lifecycle status."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Post(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "posts"
    __table_args__ = (
        Index("ix_posts_campaign_id", "campaign_id"),
        Index("ix_posts_user_id", "user_id"),
        Index("ix_posts_campaign_id_status", "campaign_id", "status"),
        Index("ix_posts_user_id_status", "user_id", "status"),
        Index("ix_posts_external_id", "external_id"),
        Index("ix_posts_target_post_id", "target_post_id"),
    )

    campaign_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("campaigns.id"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    social_account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("social_accounts.id")
    )
    platform: Mapped[str] = mapped_column(
        String(32), nullable=False, default="linkedin", server_default="linkedin"
    )
    # post | repost_comment | comment | like
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    # For amplify, the external URN being acted on. For distribute interactions,
    # target_post_id links to the local variation post; its external_id resolves
    # to the target URN once that post is published.
    target_external_id: Mapped[str | None] = mapped_column(Text)
    target_post_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("posts.id"))
    angle: Mapped[str | None] = mapped_column(Text)
    body: Mapped[str | None] = mapped_column(Text)
    body_native: Mapped[str | None] = mapped_column(Text)
    lang: Mapped[str | None] = mapped_column(String(16))
    link: Mapped[str | None] = mapped_column(Text)
    first_comment: Mapped[str | None] = mapped_column(Text)
    # Image source for this post: our stored asset (image_asset_id) or an external
    # URL (image_url). image_asset_urn is the per-author LinkedIn URN set at publish.
    image_asset_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("assets.id"))
    image_url: Mapped[str | None] = mapped_column(Text)
    image_alt: Mapped[str | None] = mapped_column(Text)
    image_asset_urn: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", server_default="pending"
    )
    idempotency_key: Mapped[str | None] = mapped_column(Text, unique=True)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    external_id: Mapped[str | None] = mapped_column(Text)
    # URN of the link-in-first-comment, when link_placement is first_comment. Set
    # after the body publishes; doubles as the idempotency marker so a retry
    # resumes at the comment instead of re-publishing the post.
    first_comment_external_id: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    retries: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
