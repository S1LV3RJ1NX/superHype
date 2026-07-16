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

# X's hard post length. Anything longer is rejected by the API, so an overlong
# generation gets one regenerate before the job fails; we never truncate
# mid-sentence.
_X_CHAR_LIMIT = 280

# Actions that carry no generated text (a like or a bookmark has no body).
_TEXTLESS_ACTIONS = ("like", "bookmark")


def _too_long(text: str, platform: str) -> bool:
    return platform == "x" and len(text) > _X_CHAR_LIMIT


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


async def _variation_batch(
    seed_content: str,
    n: int,
    *,
    tone: str | None,
    length: str | None,
    language: str | None,
    extra: str | None,
    persona: str | None,
    platform: str,
) -> list[str]:
    """One gateway call producing exactly n variation bodies (unvalidated length)."""
    system = variations_system(
        n,
        tone=tone,
        length=length,
        language=language,
        extra=extra,
        persona=persona,
        platform=platform,
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


async def generate_variations(
    seed_content: str,
    n: int,
    *,
    tone: str | None = None,
    length: str | None = None,
    language: str | None = None,
    extra: str | None = None,
    persona: str | None = None,
    platform: str = "linkedin",
) -> list[str]:
    """Produce N distinct, natural variations of the seed post.

    When `persona` is set, every variation is written in that author's team
    voice. On X the 280-character limit is enforced: overlong variations are
    regenerated once, and the job fails (rather than truncating mid-sentence)
    if the model still cannot fit.
    """
    items = await _variation_batch(
        seed_content,
        n,
        tone=tone,
        length=length,
        language=language,
        extra=extra,
        persona=persona,
        platform=platform,
    )
    overlong = [i for i, v in enumerate(items) if _too_long(v, platform)]
    if overlong:
        replacements = await _variation_batch(
            seed_content,
            len(overlong),
            tone=tone,
            length=length,
            language=language,
            extra=extra,
            persona=persona,
            platform=platform,
        )
        for pos, i in enumerate(overlong):
            items[i] = replacements[pos]
        if any(_too_long(v, platform) for v in items):
            raise GenerationError(
                "LLM could not produce post variations within X's 280-character "
                "limit after a retry."
            )
    return items


def _format_interaction_item(pos: int, item: dict[str, str]) -> str:
    """Render one numbered interaction item for the prompt, with optional persona."""
    line = (
        f"{pos}. action={item.get('action', 'comment')} "
        f"angle={item.get('angle', '') or 'natural reaction'}"
    )
    persona = " ".join((item.get("persona") or "").split())
    if persona:
        line += f" persona={persona}"
    return line


async def _interaction_chunk(
    target_text: str,
    items: list[dict[str, str]],
    chunk_indices: list[int],
    *,
    tone: str | None,
    length: str | None,
    language: str | None,
    extra: str | None,
    platform: str,
    sem: asyncio.Semaphore,
) -> list[str]:
    """Generate texts for one chunk of interaction items, with the quality retry.

    Returns the chunk's texts in chunk order. Raises GenerationError if the
    chunk cannot produce substantive, varied text (on X: within the character
    limit) after one regeneration.
    """
    enumerated = "\n".join(
        _format_interaction_item(pos, items[i]) for pos, i in enumerate(chunk_indices)
    )
    system = interactions_system(
        len(chunk_indices),
        enumerated,
        tone=tone,
        length=length,
        language=language,
        extra=extra,
        platform=platform,
    )

    async with sem:
        # The comment-quality floor: substantive, varied comments only. If the
        # model returns short or generic praise (or an over-limit tweet),
        # regenerate once before failing.
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
                or _too_long(candidate[pos], platform)
                for pos in range(len(chunk_indices))
            ):
                return candidate

    raise GenerationError(
        "LLM returned low-quality, too-long, or too-few interaction texts after "
        "a retry."
    )


async def generate_interactions(
    target_text: str,
    items: list[dict[str, str]],
    *,
    tone: str | None = None,
    length: str | None = None,
    language: str | None = None,
    extra: str | None = None,
    platform: str = "linkedin",
) -> list[str]:
    """Produce one interaction text per item (empty for `like` and `bookmark`).

    `items` is a list of {"action": ..., "angle": ...}. The output is indexed to
    the input order. Text items are split into bounded chunks generated
    concurrently, so a large campaign fans out instead of serializing one huge
    completion; if any chunk fails the whole call fails (all-or-nothing).
    """
    if not items:
        return []

    text_indices = [
        i for i, it in enumerate(items) if it.get("action") not in _TEXTLESS_ACTIONS
    ]
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
                platform=platform,
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
