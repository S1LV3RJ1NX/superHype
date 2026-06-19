"""Asset: an uploaded image stored as bytes.

Kept in its own table so the hot campaign/post tables stay lean. The bytes column
is large and TOASTed out-of-line by Postgres; never select it except to serve a
preview or to upload to LinkedIn at publish time. Storage sits behind the
AssetStore interface, so this can be swapped for object storage later.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, LargeBinary, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPrimaryKeyMixin


class Asset(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "assets"

    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
