"""Campaign API schemas (the boundary speaks schemas, not ORM objects)."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CampaignOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    type: str
    raw_brief: str | None
    seed_url: str | None
    seed_urn: str | None
    seed_content: str | None
    tone: str | None
    length: str | None
    language: str
    extra_instructions: str | None
    image_url: str | None
    image_alt: str | None
    link: str | None
    link_placement: str
    status: str
    stagger_min_seconds: int
    stagger_max_seconds: int
    created_by: uuid.UUID | None
    launched_by: uuid.UUID | None
    launched_at: datetime | None
    created_at: datetime
    updated_at: datetime


class CampaignDetail(CampaignOut):
    post_count: int = 0
    counts: dict[str, int] = {}


class ApprovalReadiness(BaseModel):
    """Pre-flight LinkedIn check for the current user on one campaign.

    Answers "can I approve my posts here, or do I need to (re)connect first?" so
    the UI can prompt for re-consent before the person starts approving instead
    of failing mid-flow. requires_linkedin is false when the user's pending posts
    are all assisted-manual (comments or likes done by hand), which need no token.
    """

    pending_count: int
    requires_linkedin: bool
    connected: bool
    needs_reconnect: bool


class CampaignCreate(BaseModel):
    title: str
    type: str = Field(pattern="^(amplify|distribute)$")
    raw_brief: str | None = None
    seed_url: str | None = None
    seed_content: str | None = None
    tone: str | None = None
    length: str | None = None
    language: str = "en"
    extra_instructions: str | None = None
    image_url: str | None = None
    image_alt: str | None = None
    link: str | None = None
    link_placement: str = "first_comment"
    stagger_min_seconds: int = 600
    stagger_max_seconds: int = 1800


class CampaignUpdate(BaseModel):
    title: str | None = None
    raw_brief: str | None = None
    seed_url: str | None = None
    seed_content: str | None = None
    tone: str | None = None
    length: str | None = None
    language: str | None = None
    extra_instructions: str | None = None
    image_url: str | None = None
    image_alt: str | None = None
    link: str | None = None
    link_placement: str | None = None
    stagger_min_seconds: int | None = None
    stagger_max_seconds: int | None = None
