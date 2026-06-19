"""Pydantic schemas for the LLM generation output contract and input brief.

The output contract matches DESIGN.md section 10 and SKILL.md.
"""

from pydantic import BaseModel


class HeroPost(BaseModel):
    account: str = ""
    platform: str = "linkedin"
    text: str
    link_placement: str = "first_comment"
    first_comment: str = ""
    hashtags: list[str] = []


class Variant(BaseModel):
    person: str
    role: str = ""
    platform: str = "linkedin"
    action: str = "post"
    angle: str = ""
    text_en: str
    text_native: str = ""
    native_language: str = ""


class CommentItem(BaseModel):
    person: str
    on: str = "hero_post"
    text_en: str
    text_native: str = ""
    native_language: str = ""


class GenerationResult(BaseModel):
    campaign: str = ""
    assumptions: str = ""
    hero_post: HeroPost
    variants: list[Variant] = []
    comments: list[CommentItem] = []


class RosterEntry(BaseModel):
    name: str
    role: str = ""
    language: str = "en"
    platform: str = "linkedin"


class GenerationBrief(BaseModel):
    title: str
    raw_brief: str
    link: str | None = None
    image_alt: str | None = None
    hero_account: str | None = None
    roster: list[RosterEntry] = []
