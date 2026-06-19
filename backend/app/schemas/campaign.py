"""Campaign API schemas (the boundary speaks schemas, not ORM objects)."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class CampaignOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    raw_brief: str
    image_url: str | None
    image_alt: str | None
    link: str | None
    link_placement: str
    hero_account_id: uuid.UUID | None
    writing_skill_id: uuid.UUID | None
    status: str
    stagger_min_seconds: int
    stagger_max_seconds: int
    created_by: uuid.UUID | None
    approved_by: uuid.UUID | None
    approved_at: datetime | None
    created_at: datetime
    updated_at: datetime
