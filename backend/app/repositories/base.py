"""Generic repository base.

All database access lives in repositories. Each method takes `db` first and returns
model instances; repositories do not commit (the controller or service owns the
transaction). The keyset `paginate` helper backs the high-volume list endpoints.
"""

import uuid
from typing import Any, Generic, TypeVar

from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from app.db.base import Base
from app.schemas.common import Page, PageParams, encode_cursor

ModelT = TypeVar("ModelT", bound=Base)


class BaseRepository(Generic[ModelT]):
    model: type[ModelT]

    async def get(self, db: AsyncSession, id: uuid.UUID) -> ModelT | None:
        return await db.get(self.model, id)

    async def list(self, db: AsyncSession, **filters: Any) -> list[ModelT]:
        stmt = select(self.model).filter_by(**filters)
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def create(self, db: AsyncSession, **fields: Any) -> ModelT:
        obj = self.model(**fields)
        db.add(obj)
        await db.flush()
        return obj

    async def update(self, db: AsyncSession, obj: ModelT, **fields: Any) -> ModelT:
        for key, value in fields.items():
            setattr(obj, key, value)
        await db.flush()
        return obj

    async def delete(self, db: AsyncSession, obj: ModelT) -> None:
        await db.delete(obj)
        await db.flush()

    async def paginate(
        self, db: AsyncSession, *, params: PageParams, **filters: Any
    ) -> Page[ModelT]:
        """Keyset paginate on (created_at, id), newest first.

        Fetches one extra row to decide whether a next page exists, and encodes the
        last returned row as the next cursor.
        """
        # All keyset-paginated models carry created_at and id (via the mixins);
        # the Base-bound TypeVar cannot express that, hence the annotations.
        created_at_col: InstrumentedAttribute = self.model.created_at  # type: ignore[attr-defined]
        id_col: InstrumentedAttribute = self.model.id  # type: ignore[attr-defined]

        stmt = select(self.model).filter_by(**filters)

        cursor = params.decoded_cursor
        if cursor is not None:
            created_at, row_id = cursor
            stmt = stmt.where(tuple_(created_at_col, id_col) < (created_at, row_id))

        stmt = stmt.order_by(created_at_col.desc(), id_col.desc()).limit(
            params.limit + 1
        )

        result = await db.execute(stmt)
        rows = list(result.scalars().all())

        next_cursor: str | None = None
        if len(rows) > params.limit:
            rows = rows[: params.limit]
            last = rows[-1]
            next_cursor = encode_cursor(last.created_at, last.id)  # type: ignore[attr-defined]

        return Page[ModelT](items=rows, next_cursor=next_cursor)
