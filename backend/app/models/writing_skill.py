"""WritingSkill: a swappable, editable LLM generation profile (a system prompt)."""

import uuid

from sqlalchemy import Boolean, Column, ForeignKey, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

_is_default_col = Column("is_default", Boolean)


class WritingSkill(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "writing_skills"
    __table_args__ = (
        Index(
            "uq_writing_skills_is_default",
            "is_default",
            unique=True,
            postgresql_where=text("is_default"),
            sqlite_where=text("is_default"),
        ),
        Index("ix_writing_skills_is_archived", "is_archived"),
        Index("ix_writing_skills_status", "status"),
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
    is_seed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="published", server_default="published"
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
