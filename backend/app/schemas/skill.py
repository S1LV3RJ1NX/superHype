"""Pydantic schemas for writing-skill CRUD."""

import uuid
from datetime import datetime

from pydantic import BaseModel


class SkillOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    name: str
    description: str | None
    instructions: str
    model: str | None
    is_default: bool
    is_archived: bool
    is_seed: bool
    status: str
    created_by: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class SkillCreate(BaseModel):
    name: str
    description: str | None = None
    instructions: str


class SkillUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    instructions: str | None = None


class GenerateInstructionsRequest(BaseModel):
    description: str


class GenerateInstructionsResponse(BaseModel):
    instructions: str


class SkillTestRequest(BaseModel):
    title: str = "Sample campaign"
    raw_brief: str = "We just launched a great new feature."


class SkillTestResponse(BaseModel):
    output: dict
