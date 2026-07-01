"""Team request/response schemas."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class TeamOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    name: str
    is_active: bool
    created_at: datetime
    member_count: int = 0


class TeamCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class TeamUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    is_active: bool | None = None
