"""Pydantic schemas for the LLM generation output contracts.

Generation is intentionally small: post variations for distribute, and varied
interaction text (comments / reshare commentary) for both flows.
"""

from pydantic import BaseModel


class VariationSet(BaseModel):
    """N distinct post bodies generated from a seed."""

    variations: list[str]


class InteractionTexts(BaseModel):
    """One text per requested interaction item, indexed to the input order."""

    texts: list[str]
