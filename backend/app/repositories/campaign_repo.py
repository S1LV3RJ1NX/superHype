"""Campaign repository: the reference aggregate for the repo/controller/view pattern."""

from app.models.campaign import Campaign
from app.repositories.base import BaseRepository


class CampaignRepository(BaseRepository[Campaign]):
    model = Campaign


campaign_repo = CampaignRepository()
