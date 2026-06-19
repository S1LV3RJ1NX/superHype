"""SlackIdentity: maps an app user to their Slack user and DM channel."""

import uuid

from sqlalchemy import ForeignKey, Index, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class SlackIdentity(TimestampMixin, Base):
    __tablename__ = "slack_identities"
    __table_args__ = (Index("ix_slack_identities_slack_user_id", "slack_user_id"),)

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    slack_user_id: Mapped[str] = mapped_column(Text, nullable=False)
    slack_dm_channel: Mapped[str | None] = mapped_column(Text)
