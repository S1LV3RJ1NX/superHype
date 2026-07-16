"""Post API schemas: output, editable fields, and the plan/assignment request."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field

from app.core.engagement import is_assisted


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
    engagement_url: str | None
    acknowledged_at: datetime | None
    external_id: str | None
    error: str | None
    retries: int
    created_at: datetime
    updated_at: datetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def assisted(self) -> bool:
        """True when this action is a guided human step, not an API call.

        Lets the client merge the assisted like+comment pair into one card
        without knowing the COMMUNITY_MANAGEMENT_ENABLED flag itself.
        """
        return is_assisted(self.action, self.platform)


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
    action: str = Field(pattern="^(post|comment|like|repost_comment|bookmark)$")
    body: str | None = None
    angle: str | None = None
    target_post_index: int | None = None


class PlanRequest(BaseModel):
    """Participants for a campaign; the backend expands each into concrete actions
    based on the campaign type (see campaign_service.expand_participants).

    ``regenerate`` forces every post to be rewritten. Left False (the default),
    re-planning preserves text for participants already in the plan and only
    generates the newly added ones, so adding a person does not overwrite edits.

    ``actions_by_participant`` is amplify only: the campaign manager picks which
    of like/comment/repost_comment each person does. When omitted, amplify
    defaults to all three per participant. Distribute ignores it and derives its
    own action graph. A participant mapped to an empty list contributes no posts.
    """

    participant_ids: list[uuid.UUID]
    regenerate: bool = False
    actions_by_participant: dict[uuid.UUID, list[str]] | None = None


class BatchAction(BaseModel):
    """Settle several posts in one atomic request.

    Backs the combined assisted like+comment card: one Approve, Mark done, or
    Skip acts on both rows together. Kept general (a list of ids plus an op) so
    the same endpoint serves the wider "approve all my actions" flow once the
    Community Management API is enabled.
    """

    op: Literal["approve", "ack", "skip"]
    # Capped so one request cannot settle an unbounded set; 100 matches the list
    # pagination limit and comfortably covers a person's actions in a campaign.
    post_ids: list[uuid.UUID] = Field(min_length=1, max_length=100)
