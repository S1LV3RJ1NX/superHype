"""Post API schemas: output, editable fields, and the plan/assignment request."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class PostOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    campaign_id: uuid.UUID
    user_id: uuid.UUID
    social_account_id: uuid.UUID | None
    platform: str
    action: str
    target_external_id: str | None
    target_post_id: uuid.UUID | None
    angle: str | None
    body: str | None
    body_native: str | None
    lang: str | None
    link: str | None
    first_comment: str | None
    image_asset_id: uuid.UUID | None
    image_url: str | None
    image_alt: str | None
    status: str
    scheduled_at: datetime | None
    published_at: datetime | None
    external_id: str | None
    error: str | None
    retries: int
    created_at: datetime
    updated_at: datetime


class PostUpdate(BaseModel):
    body: str | None = None
    body_native: str | None = None
    first_comment: str | None = None
    image_asset_id: uuid.UUID | None = None
    image_url: str | None = None
    image_alt: str | None = None


class Assignment(BaseModel):
    """One person doing one action in a campaign.

    For distribute, `post` actions become variation posts (their order defines
    variation slots); interactions reference a poster via `target_post_index`.
    """

    user_id: uuid.UUID
    action: str = Field(pattern="^(post|comment|like|repost_comment)$")
    body: str | None = None
    angle: str | None = None
    target_post_index: int | None = None


class PlanRequest(BaseModel):
    assignments: list[Assignment]
