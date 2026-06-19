"""Campaign controller: request handling and authorization.

Controllers call repositories and services and return schema objects.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.repositories.campaign_repo import campaign_repo
from app.schemas.campaign import CampaignOut
from app.schemas.common import Page, PageParams


async def list_campaigns(
    db: AsyncSession, params: PageParams, user: User
) -> Page[CampaignOut]:
    page = await campaign_repo.paginate(db, params=params)
    return Page[CampaignOut](
        items=[CampaignOut.model_validate(c) for c in page.items],
        next_cursor=page.next_cursor,
    )
