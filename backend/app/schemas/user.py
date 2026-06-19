"""User request/response schemas."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    name: str | None
    avatar_url: str | None
    role: str
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class RoleUpdate(BaseModel):
    role: Literal["admin", "editor", "viewer"]
