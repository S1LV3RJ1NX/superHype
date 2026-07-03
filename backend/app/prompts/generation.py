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


def persuasion_rules() -> str:
    """Reader-first persuasion principles shared by every generated text.

    Writing is applied psychology: the effect on the reader is the point, not the
    transmission. These are woven in alongside the author's team persona so the
    copy reads like a specific human making one compelling point, not a broadcast.
    Kept em-dash free, like all of our copy.
    """
    return (
        "Persuasion principles (write for the reader's reception, not to "
        "broadcast):\n"
        "- Start in the reader's world: open with the problem, moment, or question "
        "they already feel, not with the company, the product, or yourself.\n"
        "- The first line sets the frame: make it a person, a scene, a number, or a "
        "real question, never setup or pleasantries.\n"
        "- One core argument: commit to the single most compelling idea instead of "
        "listing several weak ones.\n"
        "- Show, then tell: lead with a concrete example or scene, then draw the "
        "point from it.\n"
        "- Stories over statistics: a specific person or moment lands harder than a "
        "percentage; use numbers to sharpen a story, not to replace it.\n"
        "- Validate, then redirect: begin from what the reader already believes and "
        "get them nodding before you shift their view.\n"
        "- Speak the audience's language: sound like a credible practitioner on "
        "LinkedIn, never a press release.\n"
        "- Omit needless words: cut 'in order to', 'it is important to note', "
        "'basically', 'actually', 'really'; if a line does not earn its place, cut "
        "it."
    )


def variations_system(
    n: int,
    *,
    tone: str | None = None,
    length: str | None = None,
    language: str | None = None,
    extra: str | None = None,
    persona: str | None = None,
) -> str:
    """System prompt for generating N distinct post variations from a seed.

    Ordering is deliberate: the composed content rules (global, then campaign)
    lead, then the code-based craft prompt, then the seed post arrives as the
    user message. The integrity rules below are non-negotiable even when a
    content rule is silent on them (never fabricate, never use em dashes).
    """
    hints = _hint_block(tone=tone, length=length, language=language)
    rules_block = f"{extra.strip()}\n\n" if extra and extra.strip() else ""
    hint_tail = f"{hints}\n\n" if hints else ""
    persona_clean = " ".join((persona or "").split())
    persona_line = (
        "Write every variation in this author's team voice and point of view, "
        f"while still following every rule below: {persona_clean}\n\n"
        if persona_clean
        else ""
    )
    return (
        f"{rules_block}"
        "You write LinkedIn posts for an employee-advocacy campaign. Given a seed "
        f"post, produce exactly {n} distinct variations that make the same core "
        "point in genuinely different voices and structures, so they do not look "
        "coordinated.\n\n"
        f"{persona_line}"
        f"{persuasion_rules()}\n\n"
        "Format and integrity rules:\n"
        "- Opinion over announcement: frame each post around a point of view or "
        "the problem it kills, not a status update.\n"
        "- Use only real numbers and details from the seed. Never invent figures, "
        "customers, partnerships, or outcomes.\n"
        "- Short sentences, plain words, short paragraphs with white space.\n"
        "- End most posts with a genuine reason to engage (a real question or a "
        "mild take).\n"
        "- Aim for roughly 120 to 200 words.\n"
        "- Never use em dashes or en dashes (the characters and the words). Use "
        "commas, periods, colons, or parentheses instead.\n"
        f"- {_banned_phrase_line()}\n\n"
        f"{hint_tail}"
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
    """System prompt for generating `count` distinct interaction texts.

    Same ordering contract as variations: the composed content rules (global,
    then campaign) lead, then the code-based craft prompt, then the post being
    reacted to arrives as the user message.
    """
    hints = _hint_block(tone=tone, length=length, language=language)
    rules_block = f"{extra.strip()}\n\n" if extra and extra.strip() else ""
    reshare_style = (
        f"For reshare commentary (action=repost_comment) only, apply this style: "
        f"{hints}\n\n"
        if hints
        else ""
    )
    return (
        f"{rules_block}"
        "You write short, natural LinkedIn interactions (comments and reshare "
        "commentary) reacting to a post. Each must be distinct and human, never "
        "templated or repetitive.\n\n"
        "Write for the reader, not to broadcast: react in their world, make one "
        "concrete point, validate before you push back, sound like a real "
        "practitioner on LinkedIn, and cut every needless word.\n\n"
        "Comment rules (action=comment):\n"
        "- React to the post's actual content. 1 to 3 sentences that add a new "
        "point, ask a real question, or share a related experience.\n"
        "- Driven by the post content, not by any tone or length preset.\n"
        "- Never restate the post, and make each text clearly different from the "
        "others.\n"
        '- Banned: generic praise such as "Great post", "Congrats team", "Love '
        'this", or "This is huge", and any one-word or emoji-only reaction.\n\n'
        "Reshare commentary rules (action=repost_comment):\n"
        "- A short framing line a person adds when resharing the post, in their "
        "own voice and specific to the post.\n\n"
        "All texts: never use em dashes or en dashes; use commas, periods, or "
        f"parentheses instead. {_banned_phrase_line()}\n\n"
        "When an item includes a persona=... field, write that text in that "
        "person's team voice and point of view, while still following every rule "
        "above.\n\n"
        f"{reshare_style}"
        f"Produce exactly {count} texts for the numbered items below, and respond "
        'with a single JSON object: {"texts": ["...", ...]} indexed to those item '
        "numbers.\n\n"
        f"Items:\n{items_block}"
    ).strip()
