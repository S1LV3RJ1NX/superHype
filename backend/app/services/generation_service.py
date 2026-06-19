"""Generation service: call the LLM gateway and parse output defensively.

Two focused jobs:
- generate_variations: N distinct post bodies from a seed (distribute).
- generate_interactions: varied comment / reshare text per participant (both flows).

Both are governed by lightweight per-campaign hints (tone, length, language) and
parse the model's JSON defensively, raising GenerationError on any failure.
"""

import json
import re
from typing import Any

from app.config import settings
from app.integrations.llm import get_llm_client
from app.schemas.generation import InteractionTexts, VariationSet


class GenerationError(Exception):
    """Raised when the LLM output cannot be parsed into a valid contract."""


_FENCE_RE = re.compile(r"^```(?:json)?\s*\n?", re.MULTILINE)
_FENCE_CLOSE_RE = re.compile(r"\n?```\s*$", re.MULTILINE)


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


def _hint_block(*, tone: str | None, length: str | None, language: str | None) -> str:
    parts = []
    if tone:
        parts.append(f"Tone: {tone}.")
    if length:
        parts.append(f"Length: {length}.")
    if language:
        parts.append(f"Write in: {language}.")
    return " ".join(parts)


async def _complete_json(messages: list[dict[str, Any]]) -> Any:
    """Call the gateway expecting a JSON object, strip fences, and parse."""
    client = get_llm_client()
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
        return json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise GenerationError(
            f"LLM returned non-JSON output: {exc}. Raw (first 200 chars): {raw[:200]}"
        ) from exc


async def generate_variations(
    seed_content: str,
    n: int,
    *,
    tone: str | None = None,
    length: str | None = None,
    language: str | None = None,
    extra: str | None = None,
) -> list[str]:
    """Produce N distinct, natural variations of the seed post."""
    hints = _hint_block(tone=tone, length=length, language=language)
    system = (
        "You write LinkedIn posts for an employee-advocacy campaign. Given a seed "
        f"post, produce exactly {n} distinct variations that say the same thing in "
        "genuinely different voices and structures, so they do not look coordinated. "
        f"{hints} {extra or ''}\n\n"
        'Respond with a single JSON object: {"variations": ["...", ...]} containing '
        f"exactly {n} strings and nothing else."
    ).strip()

    data = await _complete_json(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": seed_content},
        ]
    )
    try:
        result = VariationSet.model_validate(data)
    except Exception as exc:
        raise GenerationError(
            f"LLM output does not match the variations contract: {exc}"
        ) from exc

    items = [v.strip() for v in result.variations if v.strip()]
    if not items:
        raise GenerationError("LLM returned no usable variations.")
    # Defensively normalize to exactly n: truncate extras, pad by cycling.
    if len(items) >= n:
        return items[:n]
    return [items[i % len(items)] for i in range(n)]


async def generate_interactions(
    target_text: str,
    items: list[dict[str, str]],
    *,
    tone: str | None = None,
    length: str | None = None,
    language: str | None = None,
    extra: str | None = None,
) -> list[str]:
    """Produce one interaction text per item (empty string for `like`).

    `items` is a list of {"action": ..., "angle": ...}. The output is indexed to
    the input order.
    """
    if not items:
        return []

    text_indices = [i for i, it in enumerate(items) if it.get("action") != "like"]
    if not text_indices:
        return ["" for _ in items]

    hints = _hint_block(tone=tone, length=length, language=language)
    enumerated = "\n".join(
        f"{pos}. action={items[i].get('action', 'comment')} "
        f"angle={items[i].get('angle', '') or 'natural reaction'}"
        for pos, i in enumerate(text_indices)
    )
    system = (
        "You write short, natural LinkedIn interactions (comments and reshare "
        "commentary) reacting to a post. Each must be distinct and human, never "
        f"templated or repetitive. {hints} {extra or ''}\n\n"
        f"Produce exactly {len(text_indices)} texts for the numbered items below, "
        'and respond with a single JSON object: {"texts": ["...", ...]} indexed to '
        "those item numbers.\n\n"
        f"Items:\n{enumerated}"
    ).strip()

    data = await _complete_json(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": target_text},
        ]
    )
    try:
        result = InteractionTexts.model_validate(data)
    except Exception as exc:
        raise GenerationError(
            f"LLM output does not match the interactions contract: {exc}"
        ) from exc

    texts = result.texts
    out = ["" for _ in items]
    for pos, i in enumerate(text_indices):
        out[i] = texts[pos].strip() if pos < len(texts) else ""
    return out
