"""Content rule repository: the single global content-rules document.

One row only. Reads return that row (created empty on first access); writes
update its body. Does not commit; the controller owns the transaction.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.content_rule import ContentRule


class ContentRuleRepository:
    async def _first(self, db: AsyncSession) -> ContentRule | None:
        """The singleton row (oldest wins). Tolerates duplicates from a create race.

        There is no DB uniqueness constraint enforcing the singleton, so two
        first-time requests could insert two rows. Using LIMIT 1 (not
        scalar_one) means reads keep working instead of raising
        MultipleResultsFound forever after such a race.
        """
        return (
            (
                await db.execute(
                    select(ContentRule).order_by(ContentRule.created_at).limit(1)
                )
            )
            .scalars()
            .first()
        )

    async def get_or_create(self, db: AsyncSession) -> ContentRule:
        """Return the singleton content-rules row, creating an empty one if absent."""
        row = await self._first(db)
        if row is None:
            row = ContentRule(body=None)
            db.add(row)
            await db.flush()
        return row

    async def get_body(self, db: AsyncSession) -> str | None:
        """The current global rules body (None when unset), for the generation path."""
        row = await self._first(db)
        return row.body if row is not None else None

    async def set_body(
        self, db: AsyncSession, body: str | None, actor_id: uuid.UUID | None
    ) -> ContentRule:
        row = await self._first(db)
        if row is None:
            row = ContentRule()
            db.add(row)
        row.body = body
        row.updated_by = actor_id
        await db.flush()
        return row


content_rule_repo = ContentRuleRepository()
