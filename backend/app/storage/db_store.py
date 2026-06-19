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


db_asset_store = DBAssetStore()
