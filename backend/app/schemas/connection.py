"""Pydantic schemas for the LinkedIn connection flow."""

import uuid
from datetime import datetime

from pydantic import BaseModel


class AuthorizeUrlOut(BaseModel):
    authorize_url: str


class LinkedInCallbackBody(BaseModel):
    code: str
    state: str


class ConnectionOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    platform: str
    external_urn: str | None
    display_name: str | None
    status: str
    connected_at: datetime
    updated_at: datetime
    # Set only on a callback that resumed a pending action (reconnect-then-act),
    # so the portal can route the user back to the campaign it queued.
    resumed_post_id: uuid.UUID | None = None
    resumed_campaign_id: uuid.UUID | None = None
