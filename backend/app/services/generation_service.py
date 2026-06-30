"""Generation service: call the LLM gateway and parse output defensively.

Two focused jobs:
- generate_variations: N distinct post bodies from a seed (distribute).
- generate_interactions: varied comment / reshare text per participant (both flows).

Both are governed by lightweight per-campaign hints (tone, length, language) and
parse the model's JSON defensively, raising GenerationError on any failure.
"""

import asyncio
import json
import re
from typing import Any

from app.config import settings
from app.integrations.llm import get_llm_client
from app.prompts.generation import (
    BANNED_COMMENT_OPENERS,
    BANNED_PHRASES,
    interactions_system,
    variations_system,
)
from app.schemas.generation import InteractionTexts, VariationSet


class GenerationError(Exception):
    """Raised when the LLM output cannot be parsed into a valid contract."""


# Interactions are generated in bounded parallel chunks rather than one giant
# completion: a single call asked for hundreds of texts risks the output token
# limit, degrades quality, and fails all-or-nothing. Chunks keep each prompt
# small and let a 100-person campaign fan out instead of serializing. The
# concurrency cap protects the gateway from a thundering herd.
_INTERACTION_CHUNK_SIZE = 20
_MAX_GENERATION_CONCURRENCY = 5


_FENCE_RE = re.compile(r"^```(?:json)?\s*\n?", re.MULTILINE)
_FENCE_CLOSE_RE = re.compile(r"\n?```\s*$", re.MULTILINE)

# AGENTS.md bans em dashes in any copy, and on the 2026 feed they read as an AI
# tell. The prompts forbid them, but models slip, so we strip em and en dashes
# deterministically as a hard guarantee before the text ever reaches LinkedIn.
_DASH_BREAK_RE = re.compile(r"\s*[\u2014\u2013]\s*")
_NUM_RANGE_DASH_RE = re.compile(r"(?<=\d)\s*[\u2014\u2013]\s*(?=\d)")


def _strip_em_dashes(text: str) -> str:
    """Replace em/en dashes with natural punctuation (ranges keep a hyphen)."""
    text = _NUM_RANGE_DASH_RE.sub("-", text)
    text = _DASH_BREAK_RE.sub(", ", text)
    text = re.sub(r"\s+,", ",", text)
    return re.sub(r",\s*,", ",", text)


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


def _is_low_quality_comment(text: str) -> bool:
    """True if a comment is too short, empty, generic praise, or a banned phrase.

    These read as a coordinated pod and score near-zero on the 2026 feed, so we
    reject them and regenerate once before failing the job.
    """
    t = text.strip().lower()
    if not t:
        return True
    if len(t.split()) < settings.MIN_COMMENT_WORDS:
        return True
    stripped = t.rstrip("!.? ")
    if stripped in BANNED_COMMENT_OPENERS:
        return True
    return any(phrase in t for phrase in BANNED_PHRASES)


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
    system = variations_system(
        n, tone=tone, length=length, language=language, extra=extra
    )

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

    items = [_strip_em_dashes(v.strip()) for v in result.variations if v.strip()]
    if not items:
        raise GenerationError("LLM returned no usable variations.")
    # Defensively normalize to exactly n: truncate extras, pad by cycling.
    if len(items) >= n:
        return items[:n]
    return [items[i % len(items)] for i in range(n)]


async def _interaction_chunk(
    target_text: str,
    items: list[dict[str, str]],
    chunk_indices: list[int],
    *,
    tone: str | None,
    length: str | None,
    language: str | None,
    extra: str | None,
    sem: asyncio.Semaphore,
) -> list[str]:
    """Generate texts for one chunk of interaction items, with the quality retry.

    Returns the chunk's texts in chunk order. Raises GenerationError if the
    chunk cannot produce substantive, varied text after one regeneration.
    """
    enumerated = "\n".join(
        f"{pos}. action={items[i].get('action', 'comment')} "
        f"angle={items[i].get('angle', '') or 'natural reaction'}"
        for pos, i in enumerate(chunk_indices)
    )
    system = interactions_system(
        len(chunk_indices),
        enumerated,
        tone=tone,
        length=length,
        language=language,
        extra=extra,
    )

    async with sem:
        # The comment-quality floor: substantive, varied comments only. If the
        # model returns short or generic praise, regenerate once before failing.
        for _attempt in range(2):
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

            candidate = [t.strip() for t in result.texts]
            if len(candidate) >= len(chunk_indices) and not any(
                _is_low_quality_comment(candidate[pos])
                for pos in range(len(chunk_indices))
            ):
                return candidate

    raise GenerationError(
        "LLM returned low-quality or too-few interaction texts after a retry."
    )


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
    the input order. Text items are split into bounded chunks generated
    concurrently, so a large campaign fans out instead of serializing one huge
    completion; if any chunk fails the whole call fails (all-or-nothing).
    """
    if not items:
        return []

    text_indices = [i for i, it in enumerate(items) if it.get("action") != "like"]
    if not text_indices:
        return ["" for _ in items]

    chunks = [
        text_indices[i : i + _INTERACTION_CHUNK_SIZE]
        for i in range(0, len(text_indices), _INTERACTION_CHUNK_SIZE)
    ]
    sem = asyncio.Semaphore(_MAX_GENERATION_CONCURRENCY)
    results = await asyncio.gather(
        *(
            _interaction_chunk(
                target_text,
                items,
                chunk,
                tone=tone,
                length=length,
                language=language,
                extra=extra,
                sem=sem,
            )
            for chunk in chunks
        ),
        return_exceptions=True,
    )
    # Surface the first real failure rather than letting a partial result through.
    chunk_texts: list[list[str]] = []
    for r in results:
        if isinstance(r, BaseException):
            raise r
        chunk_texts.append(r)

    out = ["" for _ in items]
    for chunk, texts in zip(chunks, chunk_texts, strict=True):
        for pos, i in enumerate(chunk):
            out[i] = _strip_em_dashes(texts[pos]) if pos < len(texts) else ""
    return out
