"""Asset storage: a small interface plus a Postgres-backed implementation."""

from app.storage.base import AssetStore
from app.storage.db_store import db_asset_store

__all__ = ["AssetStore", "db_asset_store"]
