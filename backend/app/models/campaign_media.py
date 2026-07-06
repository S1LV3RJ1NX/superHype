"""CampaignMedia: one entry in a campaign's ordered pool of media.

A distribute campaign can carry several images, GIFs, or videos. At plan build
each poster is assigned one item by even rotation (media[i % n]), so a large
campaign does not repeat a single asset across everyone. Ordering (``position``)
is the rotation order. Rows are replaced wholesale when the campaign is saved.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPrimaryKeyMixin


class CampaignMedia(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "campaign_media"
    __table_args__ = (Index("ix_campaign_media_campaign_id", "campaign_id"),)

    campaign_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False
    )
    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assets.id"), nullable=False)
    # Rotation order within the campaign's pool (0-based).
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    alt: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
