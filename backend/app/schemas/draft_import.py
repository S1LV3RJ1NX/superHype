"""Draft import (spreadsheet) preview schemas.

The upload is never stored: the preview endpoint parses the sheet, matches rows
to the user roster, and returns this structure. The frontend echoes the matched
drafts back inside PlanRequest.manual_drafts when the plan is saved.
"""

import uuid

from pydantic import BaseModel, Field

from app.schemas.post import ManualDraft


class DraftRowMatch(BaseModel):
    """One sheet row successfully matched to a roster user."""

    row: int
    email: str | None
    name: str | None
    user_id: uuid.UUID
    user_name: str | None
    user_email: str
    matched_by: str  # "email" or "name"
    draft: ManualDraft
    warnings: list[str] = Field(default_factory=list)


class DraftRowUnmatched(BaseModel):
    """One sheet row that could not be matched; it falls back to AI."""

    row: int
    email: str | None
    name: str | None
    reason: str


class DraftImportPreview(BaseModel):
    matched: list[DraftRowMatch]
    unmatched: list[DraftRowUnmatched]
