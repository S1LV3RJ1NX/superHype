"""Prompt builders for post-variation and interaction generation.

The craft rules here are salvaged from the retired SKILL.md: hook-first,
opinion over announcement, specificity, human voice, a reason to engage, and a
hard ban on buzzwords and generic praise. Early substantive engagement is what
the feed rewards, and varied human-sounding copy is what keeps a coordinated
push from reading as a pod.
"""

# Buzzwords to avoid in any generated copy (post bodies and interactions). Also
# used by the comment-quality validator to reject low-value output.
BANNED_PHRASES: tuple[str, ...] = (
    "excited to announce",
    "thrilled to share",
    "game-changer",
    "game changer",
    "revolutionary",
    "disrupt",
    "synergy",
    "in today's fast-paced world",
    "we are proud to",
    "needle-moving",
    "best-in-class",
    "thought leader",
)

# Generic, low-value comment phrases that score near-zero and read as a pod.
# Used as prompt guidance and by the validator (exact / near-exact match).
BANNED_COMMENT_OPENERS: tuple[str, ...] = (
    "great post",
    "great launch",
    "congrats",
    "congratulations",
    "congrats team",
    "this is huge",
    "love this",
    "well said",
    "so true",
    "amazing",
    "awesome",
    "nice one",
    "fantastic",
    "this is great",
)


def _hint_block(*, tone: str | None, length: str | None, language: str | None) -> str:
    parts: list[str] = []
    if tone:
        parts.append(f"Tone: {tone}.")
    if length:
        parts.append(f"Length: {length}.")
    if language:
        parts.append(f"Write in: {language}.")
    return " ".join(parts)


def _banned_phrase_line() -> str:
    joined = ", ".join(f'"{p}"' for p in BANNED_PHRASES)
    return f"Never use these phrases, in any language: {joined}."


def variations_system(
    n: int,
    *,
    tone: str | None = None,
    length: str | None = None,
    language: str | None = None,
    extra: str | None = None,
) -> str:
    """System prompt for generating N distinct post variations from a seed."""
    hints = _hint_block(tone=tone, length=length, language=language)
    return (
        "You write LinkedIn posts for an employee-advocacy campaign. Given a seed "
        f"post, produce exactly {n} distinct variations that say the same thing in "
        "genuinely different voices and structures, so they do not look "
        "coordinated.\n\n"
        "Craft rules:\n"
        "- Hook first: the opening line must earn the click. Lead with a claim, a "
        "number, a tension, or a contrarian point, never pleasantries or setup.\n"
        "- Opinion over announcement: frame it around a point of view, the problem "
        "it kills, or the belief behind it.\n"
        "- Specific and concrete: use only real numbers and details from the seed. "
        "Never invent figures, customers, partnerships, or outcomes.\n"
        "- Human voice: short sentences, plain words, short paragraphs with white "
        "space. No press-release register and no buzzword soup.\n"
        "- End most posts with a genuine reason to engage (a real question or a "
        "mild take).\n"
        "- Aim for roughly 120 to 200 words.\n"
        f"- {_banned_phrase_line()}\n\n"
        f"{hints} {extra or ''}\n\n"
        'Respond with a single JSON object: {"variations": ["...", ...]} '
        f"containing exactly {n} strings and nothing else."
    ).strip()


def interactions_system(
    count: int,
    items_block: str,
    *,
    tone: str | None = None,
    length: str | None = None,
    language: str | None = None,
    extra: str | None = None,
) -> str:
    """System prompt for generating `count` distinct interaction texts."""
    hints = _hint_block(tone=tone, length=length, language=language)
    return (
        "You write short, natural LinkedIn interactions (comments and reshare "
        "commentary) reacting to a post. Each must be distinct and human, never "
        "templated or repetitive.\n\n"
        "Comment rules:\n"
        "- 1 to 3 sentences that add a new point, ask a real question, or share a "
        "related experience. Be specific to the post's actual content.\n"
        "- Never restate the post, and make each text clearly different from the "
        "others.\n"
        '- Banned: generic praise such as "Great post", "Congrats team", "Love '
        'this", or "This is huge", and any one-word or emoji-only reaction.\n'
        f"- {_banned_phrase_line()}\n\n"
        f"{hints} {extra or ''}\n\n"
        f"Produce exactly {count} texts for the numbered items below, and respond "
        'with a single JSON object: {"texts": ["...", ...]} indexed to those item '
        "numbers.\n\n"
        f"Items:\n{items_block}"
    ).strip()
