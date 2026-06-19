"""AuditLog: append-only record of every externally triggered mutation."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPrimaryKeyMixin


class AuditLog(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "audit_log"
    __table_args__ = (
        Index("ix_audit_log_campaign_id_created_at", "campaign_id", "created_at"),
        Index("ix_audit_log_created_at", "created_at"),
    )

    campaign_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("campaigns.id"))
    post_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("posts.id"))
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(Text, nullable=False)
    detail: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB().with_variant(JSON(), "sqlite")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
