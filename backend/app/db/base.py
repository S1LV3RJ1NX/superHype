"""Declarative base, constraint naming convention, and shared column mixins.

A stable naming convention keeps Alembic autogenerate deterministic (named
indexes, constraints, and foreign keys) which matters for clean downgrades.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, MetaData, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class UUIDPrimaryKeyMixin:
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)


def _utcnow() -> datetime:
    return datetime.now(UTC)


class TimestampMixin:
    # Python-side default and onupdate (alongside the SQL server_default): the
    # value is set on the in-memory object during flush, so callers can serialize
    # the row right after commit without a db.refresh round trip. A SQL-only
    # default/onupdate leaves the attribute expired (the DB computed it), and
    # reading it then attempts async IO during serialization, which fails with
    # MissingGreenlet outside a greenlet context.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        server_default=func.now(),
        onupdate=_utcnow,
        nullable=False,
    )
