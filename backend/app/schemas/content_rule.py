"""Content rule API schemas (the global generation-rules document)."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ContentRuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    body: str | None
    updated_by: uuid.UUID | None
    updated_at: datetime


class ContentRuleUpdate(BaseModel):
    body: str | None = None
