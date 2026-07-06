"""Postgres-backed AssetStore: image bytes live in the assets table.

The bytes column is fetched only here (serve/publish), never in metadata reads,
so the hot tables and list queries stay lean.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.asset import Asset


class DBAssetStore:
    async def put(
        self,
        db: AsyncSession,
        *,
        data: bytes,
        content_type: str,
        created_by: uuid.UUID | None = None,
    ) -> uuid.UUID:
        asset = Asset(
            content_type=content_type,
            size_bytes=len(data),
            data=data,
            created_by=created_by,
        )
        db.add(asset)
        await db.flush()
        return asset.id

    async def get(self, db: AsyncSession, asset_id: uuid.UUID) -> tuple[bytes, str]:
        stmt = select(Asset.data, Asset.content_type).where(Asset.id == asset_id)
        row = (await db.execute(stmt)).first()
        if row is None:
            raise KeyError(asset_id)
        return row.data, row.content_type

    async def content_types(
        self, db: AsyncSession, asset_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, str]:
        """Return {asset_id: content_type} for the given ids (bytes not loaded).

        Missing ids are simply absent from the result, so callers can detect
        unknown assets without fetching the large bytes column.
        """
        if not asset_ids:
            return {}
        stmt = select(Asset.id, Asset.content_type).where(Asset.id.in_(asset_ids))
        return {row.id: row.content_type for row in (await db.execute(stmt)).all()}


db_asset_store = DBAssetStore()
