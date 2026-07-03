"""Global content rules: one admin-editable document applied to all generation.

A singleton (one row). The markdown body is injected into every campaign's
generation prompts (self-posts, comments, and reshares) alongside any
per-campaign rules, so the whole org shares one baseline voice and policy.
"""

import uuid

from sqlalchemy import ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ContentRule(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "content_rules"

    body: Mapped[str | None] = mapped_column(Text)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
