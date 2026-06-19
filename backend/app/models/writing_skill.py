"""WritingSkill: a swappable, editable LLM generation profile (a system prompt)."""

import uuid

from sqlalchemy import Boolean, ForeignKey, Index, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class WritingSkill(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "writing_skills"
    __table_args__ = (
        # At most one default skill across the table.
        Index(
            "uq_writing_skills_is_default",
            "is_default",
            unique=True,
            postgresql_where="is_default",
        ),
        Index("ix_writing_skills_is_archived", "is_archived"),
    )

    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    instructions: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str | None] = mapped_column(Text)
    is_default: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    is_archived: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
