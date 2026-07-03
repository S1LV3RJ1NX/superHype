"""Content rules routes: the global generation-rules document (admin only)."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.controllers import content_rule_controller
from app.core.deps import require_role
from app.db.session import get_db
from app.models.user import User
from app.schemas.content_rule import ContentRuleOut, ContentRuleUpdate

router = APIRouter(prefix="/v1/content-rules", tags=["content-rules"])


@router.get("", response_model=ContentRuleOut)
async def get_content_rules(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_role("admin")),
) -> ContentRuleOut:
    """The global content rules applied to every campaign's generation."""
    return await content_rule_controller.get_rules(db)


@router.put("", response_model=ContentRuleOut)
async def update_content_rules(
    body: ContentRuleUpdate,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_role("admin")),
) -> ContentRuleOut:
    return await content_rule_controller.update_rules(db, body.body, actor)
