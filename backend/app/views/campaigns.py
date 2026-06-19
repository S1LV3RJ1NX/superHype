"""Campaigns router. Thin: declares deps, parses params, calls the controller.

The reference end-to-end slice for the repository/controller/view pattern and the
PageParams/Page[T] keyset pagination contract.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.controllers import campaign_controller
from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.campaign import CampaignOut
from app.schemas.common import Page, PageParams

router = APIRouter(prefix="/v1/campaigns", tags=["campaigns"])


@router.get("", response_model=Page[CampaignOut])
async def list_campaigns(
    params: PageParams = Depends(),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Page[CampaignOut]:
    return await campaign_controller.list_campaigns(db, params, user)
