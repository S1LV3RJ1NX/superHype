"""Content rule controller: read and update the global generation-rules document.

The route-level require_role("admin") is the gate; this layer does the work,
audits the change, and owns the commit.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.repositories import audit_repo
from app.repositories.content_rule_repo import content_rule_repo
from app.schemas.content_rule import ContentRuleOut


async def get_rules(db: AsyncSession) -> ContentRuleOut:
    row = await content_rule_repo.get_or_create(db)
    await db.commit()
    await db.refresh(row)
    return ContentRuleOut.model_validate(row)


async def update_rules(
    db: AsyncSession, body: str | None, actor: User
) -> ContentRuleOut:
    row = await content_rule_repo.set_body(db, body, actor_id=actor.id)
    await audit_repo.record(
        db,
        actor_id=actor.id,
        action="content_rules_updated",
        detail={"length": len(body or "")},
    )
    await db.commit()
    await db.refresh(row)
    return ContentRuleOut.model_validate(row)
