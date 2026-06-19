"""Generation service: call the LLM gateway and parse the output defensively.

Returns a validated GenerationResult. Persisting to posts rows lands with the
campaign lifecycle.
"""

import json
import re
from typing import Any

from app.config import settings
from app.integrations.llm import get_llm_client
from app.models.writing_skill import WritingSkill
from app.schemas.generation import GenerationBrief, GenerationResult


class GenerationError(Exception):
    """Raised when the LLM output cannot be parsed into a valid contract."""


_FENCE_RE = re.compile(r"^```(?:json)?\s*\n?", re.MULTILINE)
_FENCE_CLOSE_RE = re.compile(r"\n?```\s*$", re.MULTILINE)


_OUTPUT_CONTRACT = """\
You MUST respond with a single JSON object matching this exact schema:
{
  "campaign": "string",
  "assumptions": "string",
  "hero_post": {
    "account": "string",
    "platform": "string",
    "text": "string",
    "link_placement": "first_comment | body",
    "first_comment": "string",
    "hashtags": ["string"]
  },
  "variants": [
    {
      "person": "string",
      "role": "string",
      "platform": "string",
      "action": "post",
      "angle": "string",
      "text_en": "string",
      "text_native": "string",
      "native_language": "string"
    }
  ],
  "comments": [
    {
      "person": "string",
      "on": "hero_post | variant_person_name",
      "text_en": "string",
      "text_native": "string",
      "native_language": "string"
    }
  ]
}
Do not include any text outside the JSON object. Do not wrap it in markdown fences.
"""


def _safe_exc(exc: Exception) -> str:
    """Return a log-safe summary, stripping anything that looks like a token."""
    msg = str(exc)
    if len(msg) > 200:
        msg = msg[:200] + "..."
    return re.sub(r"(Bearer\s+|api_key=)[^\s'\"]+", r"\1[REDACTED]", msg)


def _strip_fences(text: str) -> str:
    text = _FENCE_RE.sub("", text)
    text = _FENCE_CLOSE_RE.sub("", text)
    return text.strip()


_META_PROMPT = """\
You are an expert prompt engineer for an employee-advocacy platform called Super-Hype.

The user will describe the kind of LinkedIn posts they want a writing skill to produce.
Your job is to generate a complete, production-ready system prompt (the "instructions"
field of a WritingSkill) that will guide an LLM to generate social media content.

Write ONLY the system prompt text covering tone, voice, structure, and length constraints.
Do NOT include the JSON output schema -- the system appends it automatically.
Do not wrap it in markdown fences or quotes.
"""


async def draft_instructions(description: str) -> str:
    """Use the LLM to draft skill instructions from a plain-language description."""
    client = get_llm_client()

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": _META_PROMPT},
        {"role": "user", "content": description},
    ]

    try:
        response = await client.chat.completions.create(
            model=settings.LLM_MODEL_NAME,
            messages=messages,  # type: ignore[arg-type]
        )
    except Exception as exc:
        raise GenerationError(
            f"LLM gateway call failed: {type(exc).__name__}: {_safe_exc(exc)}"
        ) from exc

    return response.choices[0].message.content or ""


async def generate(skill: WritingSkill, brief: GenerationBrief) -> GenerationResult:
    """Build messages, call the gateway, parse and validate the response."""
    client = get_llm_client()

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": skill.instructions + "\n\n" + _OUTPUT_CONTRACT},
        {"role": "user", "content": brief.model_dump_json()},
    ]

    try:
        response = await client.chat.completions.create(  # type: ignore[call-overload]
            model=settings.LLM_MODEL_NAME,
            messages=messages,
            response_format={"type": "json_object"},
        )
    except Exception as exc:
        raise GenerationError(
            f"LLM gateway call failed: {type(exc).__name__}: {_safe_exc(exc)}"
        ) from exc

    raw = response.choices[0].message.content or ""
    cleaned = _strip_fences(raw)

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise GenerationError(
            f"LLM returned non-JSON output: {exc}. Raw (first 200 chars): {raw[:200]}"
        ) from exc

    try:
        return GenerationResult.model_validate(data)
    except Exception as exc:
        raise GenerationError(
            f"LLM output does not match the generation contract: {exc}"
        ) from exc
