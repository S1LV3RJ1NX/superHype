"""Campaign media repository: the ordered media pool for a campaign.

One row per media item, ordered by ``position``. The pool is edited wholesale
(replace all rows) when a campaign is saved, so there is no per-item update.
"""

import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.campaign_media import CampaignMedia


class CampaignMediaRepository:
    async def list_for_campaign(
        self, db: AsyncSession, campaign_id: uuid.UUID
    ) -> list[CampaignMedia]:
        """Return the campaign's media pool in rotation order (position ascending)."""
        stmt = (
            select(CampaignMedia)
            .where(CampaignMedia.campaign_id == campaign_id)
            .order_by(CampaignMedia.position)
        )
        return list((await db.execute(stmt)).scalars().all())

    async def delete_for_campaign(
        self, db: AsyncSession, campaign_id: uuid.UUID
    ) -> None:
        """Remove the campaign's whole media pool (used when deleting a campaign)."""
        await db.execute(
            delete(CampaignMedia).where(CampaignMedia.campaign_id == campaign_id)
        )
        await db.flush()

    async def replace_for_campaign(
        self,
        db: AsyncSession,
        campaign_id: uuid.UUID,
        items: list[tuple[uuid.UUID, str | None]],
    ) -> list[CampaignMedia]:
        """Replace the whole pool with ``items`` (each ``(asset_id, alt)``).

        Position is the item's index in the given list, which is the rotation
        order at plan build. Does not commit; the controller owns the transaction.
        """
        await db.execute(
            delete(CampaignMedia).where(CampaignMedia.campaign_id == campaign_id)
        )
        rows = [
            CampaignMedia(
                campaign_id=campaign_id, asset_id=asset_id, position=idx, alt=alt
            )
            for idx, (asset_id, alt) in enumerate(items)
        ]
        for row in rows:
            db.add(row)
        await db.flush()
        return rows


campaign_media_repo = CampaignMediaRepository()
