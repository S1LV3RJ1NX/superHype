"""AssetStore: the storage boundary for uploaded image bytes.

A single small Protocol so the API and worker depend on the interface, not on
where bytes physically live. The Postgres-backed implementation ships now;
object storage or TrueFoundry can be dropped in later without touching callers.
"""

import uuid
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession


class AssetStore(Protocol):
    async def put(
        self,
        db: AsyncSession,
        *,
        data: bytes,
        content_type: str,
        created_by: uuid.UUID | None = None,
    ) -> uuid.UUID:
        """Store bytes and return the asset id."""
        ...

    async def get(self, db: AsyncSession, asset_id: uuid.UUID) -> tuple[bytes, str]:
        """Return (data, content_type) for an asset. Raises KeyError if missing."""
        ...
