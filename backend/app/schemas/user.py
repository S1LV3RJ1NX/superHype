"""User request/response schemas."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class UserOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    email: str
    name: str | None
    avatar_url: str | None
    role: str
    is_active: bool
    created_at: datetime
    team_id: uuid.UUID | None = None
    team_name: str | None = None
    linkedin_status: str | None = None
    x_status: str | None = None
    auto_approve_consented_at: datetime | None = None
    # Whether the deployment offers auto-approve at all (MANUAL_APPROVAL_ONLY
    # off), so the UI shows the consent toggle only when it would take effect.
    auto_approve_available: bool = False
    auto_approve_delay_seconds: int = 0


class AutoApproveUpdate(BaseModel):
    enabled: bool


class RoleUpdate(BaseModel):
    role: Literal["admin", "editor", "viewer"]


class TeamAssign(BaseModel):
    team_id: uuid.UUID
