"""Campaign service: state machine, plan building, and completion.

Owns the campaign status transitions and the translation of an assignment plan
into post rows (with optional LLM fill). Repositories do the DB access; this
layer owns the multi-step logic and writes audit rows.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.logger import get_logger
from app.models.campaign import Campaign
from app.models.post import Post
from app.repositories import audit_repo
from app.repositories.campaign_repo import campaign_repo
from app.repositories.content_rule_repo import content_rule_repo
from app.repositories.post_repo import post_repo
from app.repositories.social_account_repo import social_account_repo
from app.repositories.team_repo import team_repo
from app.repositories.user_repo import user_repo
from app.schemas.post import Assignment
from app.services.generation_service import (
    generate_interactions,
    generate_variations,
)

log = get_logger(__name__)


def _effective_rules(global_body: str | None, campaign: Campaign) -> str | None:
    """Combine the global content rules with the campaign's own rules for the LLM.

    The org-wide rules lead (unless the campaign opted out with
    apply_global_rules=False), then the campaign-specific rules, then any legacy
    extra_instructions. Each block is labeled so the model can tell them apart.
    Returns None when nothing applies, so the prompt stays clean.
    """
    parts: list[str] = []
    if campaign.apply_global_rules and global_body and global_body.strip():
        parts.append(
            "Organization content rules (always apply):\n" + global_body.strip()
        )
    if campaign.custom_rules and campaign.custom_rules.strip():
        parts.append("Campaign-specific rules:\n" + campaign.custom_rules.strip())
    if campaign.extra_instructions and campaign.extra_instructions.strip():
        parts.append(campaign.extra_instructions.strip())
    return "\n\n".join(parts) or None


class TransitionError(Exception):
    """Raised when a campaign status transition is not allowed."""


# Legal campaign status transitions. No `approved` state: launch is gated per
# participant, not by an admin sign-off.
TRANSITIONS: dict[str, set[str]] = {
    "draft": {"generating", "review"},
    "generating": {"review", "failed"},
    "review": {"generating", "publishing"},
    # A launched campaign can be paused; pause halts all worker fan-out until it
    # is resumed back to publishing.
    "publishing": {"completed", "failed", "paused"},
    "paused": {"publishing"},
    # Retrying a failed post reopens a completed campaign so the worker can run
    # again and check_completion can settle it once more.
    "completed": {"publishing"},
    "failed": set(),
}


async def delete_campaign(
    db: AsyncSession,
    campaign: Campaign,
    *,
    actor_id: uuid.UUID | None = None,
) -> None:
    """Delete a campaign and everything that references it.

    The FKs from posts and audit_log to campaigns have no ON DELETE rule, so the
    children are removed first. The final `campaign_deleted` audit row carries a
    null campaign_id (the row is gone) with the identity in `detail`. The caller
    owns the commit.
    """
    detail = {
        "id": str(campaign.id),
        "title": campaign.title,
        "type": campaign.type,
    }
    await audit_repo.delete_for_campaign(db, campaign.id)
    await post_repo.delete_all_for_campaign(db, campaign.id)
    await campaign_repo.delete(db, campaign)
    await audit_repo.record(
        db,
        actor_id=actor_id,
        action="campaign_deleted",
        detail=detail,
    )


async def transition(
    db: AsyncSession,
    campaign: Campaign,
    target: str,
    *,
    actor_id: uuid.UUID | None = None,
) -> Campaign:
    allowed = TRANSITIONS.get(campaign.status, set())
    if target not in allowed:
        raise TransitionError(
            f"Cannot move campaign from {campaign.status} to {target}."
        )
    await campaign_repo.set_status(db, campaign, target)
    await audit_repo.record(
        db,
        actor_id=actor_id,
        action="campaign_status_changed",
        campaign_id=campaign.id,
        detail={"to": target},
    )
    return campaign


async def reset_for_rerun(
    db: AsyncSession,
    campaign: Campaign,
    *,
    actor_id: uuid.UUID | None = None,
) -> int:
    """Rewind a launched campaign back to review so it can be launched again.

    Every post returns to pending (publish artifacts wiped) and the campaign
    returns to review with its launch cleared. This is deliberately outside the
    normal TRANSITIONS matrix: it is an admin override that can rewind from any
    launched state (publishing, paused, completed, failed). Because the campaign
    is back in review, the worker guards (which no-op for a paused or review
    campaign) drop any jobs still deferred from the previous run, so no stale
    publish or DM fires after a reset. The plan itself (post rows and bodies) is
    kept. The caller owns the commit.
    """
    from_status = campaign.status
    rewound = await post_repo.rewind_for_campaign(db, campaign.id)
    await campaign_repo.update(
        db, campaign, status="review", launched_at=None, launched_by=None
    )
    await audit_repo.record(
        db,
        actor_id=actor_id,
        action="campaign_reset",
        campaign_id=campaign.id,
        detail={"posts_rewound": rewound, "from_status": from_status},
    )
    return rewound


async def _personas_by_user(
    db: AsyncSession, user_ids: list[uuid.UUID]
) -> dict[uuid.UUID, str]:
    """Map each user to their team's persona text (empty teams are skipped)."""
    users = await user_repo.list_by_ids(db, list(set(user_ids)))
    team_ids = [u.team_id for u in users if u.team_id is not None]
    personas = await team_repo.personas_for(db, team_ids)
    result: dict[uuid.UUID, str] = {}
    for u in users:
        persona = personas.get(u.team_id) if u.team_id is not None else None
        if persona:
            result[u.id] = persona
    return result


def _resolve_interaction_target(
    campaign: Campaign, a: Assignment, poster_rows: list[Post]
) -> tuple[uuid.UUID | None, str | None]:
    """Return (target_post_id, target_external_id) for one interaction.

    Distribute interactions point at a local variation slot (default the first);
    amplify interactions point at the campaign's external seed URN.
    """
    if campaign.type == "distribute" and poster_rows:
        slot = a.target_post_index if a.target_post_index is not None else 0
        slot = max(0, min(slot, len(poster_rows) - 1))
        return poster_rows[slot].id, None
    return None, campaign.seed_urn


async def _resolve_interaction_texts(
    campaign: Campaign,
    interaction_assignments: list[Assignment],
    poster_rows: list[Post],
    persona_by_user: dict[uuid.UUID, str],
    *,
    generate: bool,
    extra: str | None = None,
    preserved: list[str | None] | None = None,
) -> list[str]:
    """Produce one text per interaction, aligned to input order.

    When generating, comments and reshares are written from the body of the post
    they react to (the distribute variation, or the campaign seed text for
    amplify), and carry the actor's team persona. Interactions are grouped by
    their target text so each LLM call reasons about a single post.

    ``preserved`` carries text kept from a prior plan (an unchanged participant's
    edited or previously generated comment): a non-None entry is used as-is and
    never regenerated, so re-planning after adding or removing a person only
    calls the LLM for the genuinely new interactions.
    """
    if not interaction_assignments:
        return []
    kept: list[str | None] = (
        list(preserved)
        if preserved is not None
        else [None] * len(interaction_assignments)
    )
    if not generate:
        return [
            k if k is not None else (a.body or "")
            for k, a in zip(kept, interaction_assignments, strict=False)
        ]

    def _target_text(a: Assignment) -> str:
        if campaign.type == "distribute" and poster_rows:
            slot = a.target_post_index if a.target_post_index is not None else 0
            slot = max(0, min(slot, len(poster_rows) - 1))
            body = poster_rows[slot].body or ""
            if body.strip():
                return body
        return campaign.seed_content or campaign.title or ""

    # Only the entries without preserved text need a gateway call.
    groups: dict[str, list[int]] = {}
    for idx, a in enumerate(interaction_assignments):
        if kept[idx] is not None:
            continue
        groups.setdefault(_target_text(a), []).append(idx)

    texts: list[str] = [t if t is not None else "" for t in kept]
    for target_text, idxs in groups.items():
        items = [
            {
                "action": interaction_assignments[j].action,
                "angle": interaction_assignments[j].angle or "",
                "persona": persona_by_user.get(interaction_assignments[j].user_id, ""),
            }
            for j in idxs
        ]
        out = await generate_interactions(
            target_text,
            items,
            tone=campaign.tone,
            length=campaign.length,
            language=campaign.language,
            extra=extra,
        )
        for pos, j in enumerate(idxs):
            texts[j] = out[pos] if pos < len(out) else ""
    return texts


async def _founder_flags(
    db: AsyncSession, user_ids: list[uuid.UUID]
) -> dict[uuid.UUID, bool]:
    """Map each user to whether their team is a founder team (for engagement order)."""
    users = await user_repo.list_by_ids(db, list(set(user_ids)))
    team_ids = [u.team_id for u in users if u.team_id is not None]
    names = await team_repo.names_for(db, team_ids)
    founders = settings.founder_team_names
    result: dict[uuid.UUID, bool] = {}
    for u in users:
        name = names.get(u.team_id) if u.team_id is not None else None
        result[u.id] = bool(name and name.lower() in founders)
    return result


# Amplify actions in canonical order, so a person's chosen subset is expanded
# in a stable sequence regardless of how the client listed them.
_AMPLIFY_ACTIONS: tuple[str, ...] = ("like", "comment", "repost_comment")


async def expand_participants(
    db: AsyncSession,
    campaign: Campaign,
    participant_ids: list[uuid.UUID],
    *,
    actions_by_participant: dict[uuid.UUID, list[str]] | None = None,
) -> list[Assignment]:
    """Turn a participant list into concrete actions from the campaign type.

    Amplify: each member does the actions chosen for them (like, comment, and/or
    repost); when ``actions_by_participant`` has no entry for a person they do all
    three, and an explicit empty list means they contribute nothing. Distribute:
    every member authors their own post (its slot is their position in the list),
    then likes and comments on up to DISTRIBUTE_MAX_ENGAGEMENT_TARGETS other
    members' posts, founder-authored posts first, so a big campaign cannot fan out
    quadratically (``actions_by_participant`` is ignored for distribute).
    """
    # Dedupe while preserving order so poster slots are stable and predictable.
    seen: set[uuid.UUID] = set()
    ordered: list[uuid.UUID] = []
    for uid in participant_ids:
        if uid not in seen:
            seen.add(uid)
            ordered.append(uid)
    if not ordered:
        return []

    out: list[Assignment] = []
    if campaign.type == "amplify":
        for uid in ordered:
            chosen = (
                actions_by_participant.get(uid)
                if actions_by_participant is not None
                else None
            )
            # No entry -> all three; an entry (even empty) is taken literally so a
            # manager can drop an action for one person. Canonical order + subset
            # filter also drops any unknown action the client might send.
            actions = [a for a in _AMPLIFY_ACTIONS if chosen is None or a in chosen]
            for action in actions:
                out.append(Assignment(user_id=uid, action=action))
        return out

    # Distribute: one authored post per member, in list order (slot = index).
    for uid in ordered:
        out.append(Assignment(user_id=uid, action="post"))

    is_founder = await _founder_flags(db, ordered)
    cap = max(0, settings.DISTRIBUTE_MAX_ENGAGEMENT_TARGETS)
    for i, uid in enumerate(ordered):
        others = [j for j in range(len(ordered)) if j != i]
        # Stable sort keeps list order within each group, founders first.
        others.sort(key=lambda j: 0 if is_founder.get(ordered[j], False) else 1)
        for j in others[:cap]:
            out.append(Assignment(user_id=uid, action="like", target_post_index=j))
            out.append(Assignment(user_id=uid, action="comment", target_post_index=j))
    return out


def _assignment_key(campaign: Campaign, a: Assignment, ordered: list[uuid.UUID]) -> str:
    """A stable identity for one action, independent of post-row uuids.

    Keyed by (action, actor, target person or seed) so the same person doing the
    same thing to the same target maps to the same key across re-plans, letting
    an edited or already-generated body carry over. Slot indexes are resolved to
    the target user so re-ordering participants does not lose a preserved body.
    """
    if a.action in ("post", "self_comment"):
        return f"{a.action}:{a.user_id}"
    if campaign.type == "distribute" and ordered and a.target_post_index is not None:
        slot = max(0, min(a.target_post_index, len(ordered) - 1))
        target = str(ordered[slot])
    else:
        target = "seed"
    return f"{a.action}:{a.user_id}:{target}"


async def _preserved_bodies(
    db: AsyncSession, campaign: Campaign, campaign_id: uuid.UUID
) -> dict[str, str]:
    """Map assignment keys to the bodies of the current pending posts.

    Read before the pending rows are cleared so a rebuild can reuse text for
    unchanged actions (no gateway call, no lost manual edit). Interaction targets
    resolve through the existing poster rows to the target person.
    """
    existing = await post_repo.list_for_campaign(db, campaign_id)
    poster_user_by_id = {p.id: p.user_id for p in existing if p.action == "post"}
    preserved: dict[str, str] = {}
    for p in existing:
        if p.status not in ("pending", "scheduled"):
            continue
        if not (p.body and p.body.strip()):
            continue
        if p.action in ("post", "self_comment"):
            key = f"{p.action}:{p.user_id}"
        elif p.target_post_id is not None:
            target_user = poster_user_by_id.get(p.target_post_id)
            key = f"{p.action}:{p.user_id}:{target_user if target_user else '?'}"
        else:
            key = f"{p.action}:{p.user_id}:seed"
        preserved[key] = p.body
    return preserved


async def build_plan(
    db: AsyncSession,
    campaign_id: uuid.UUID,
    assignments: list[Assignment],
    *,
    generate: bool,
    regenerate: bool = False,
    actor_id: uuid.UUID | None = None,
) -> list[Post]:
    """Create post rows from an assignment plan, optionally filling text via LLM.

    Incremental by default: text for actions that already exist in the current
    plan (an unchanged participant's post or comment) is preserved, so adding or
    removing a person only generates the new actions and never overwrites an edit
    or a de-selected person's already-approved work. Pass ``regenerate=True`` to
    discard preserved text and rewrite everything (used when the seed material or
    generation hints changed). Only pending/scheduled rows are rebuilt; published,
    failed, or skipped posts are never touched. Moves the campaign to `review`.
    """
    campaign = await campaign_repo.get(db, campaign_id)
    if campaign is None:
        raise TransitionError("Campaign not found.")

    preserved = {} if regenerate else await _preserved_bodies(db, campaign, campaign_id)

    # Detach any audit rows that still point at the pending posts (e.g. after a
    # reset, which rewinds rather than deletes) so the rebuild's hard-delete does
    # not trip fk_audit_log_post_id_posts.
    await audit_repo.detach_pending_posts(db, campaign_id)
    await post_repo.delete_pending_for_campaign(db, campaign_id)

    post_assignments = [a for a in assignments if a.action == "post"]
    interaction_assignments = [a for a in assignments if a.action != "post"]
    # The ordered author list backs slot -> target-user resolution for keys.
    ordered = [a.user_id for a in post_assignments]

    # Resolve each participant's LinkedIn account once.
    account_by_user: dict[uuid.UUID, uuid.UUID | None] = {}
    for a in assignments:
        if a.user_id not in account_by_user:
            acct = await social_account_repo.get_by_user(db, a.user_id)
            account_by_user[a.user_id] = acct.id if acct else None

    # Team persona per acting user, so generated comments and reposts read in that
    # team's voice. Only needed when we actually call the LLM.
    persona_by_user: dict[uuid.UUID, str] = {}
    effective_rules: str | None = None
    if generate:
        persona_by_user = await _personas_by_user(db, [a.user_id for a in assignments])
        # Global content rules (unless the campaign opted out) plus the campaign's
        # own rules, applied to every generated self-post, comment, and reshare.
        global_body = await content_rule_repo.get_body(db)
        effective_rules = _effective_rules(global_body, campaign)

    # Variation bodies must be resolved before interactions: a distribute comment
    # is written from the body of the post it reacts to, so the poster rows have
    # to exist first. Text preserved from the prior plan is reused as-is; manual
    # text (generate=False) falls back to the assignment; only the remaining slots
    # touch the gateway.
    variation_bodies: list[str] = []
    if post_assignments:
        variation_bodies = [
            preserved.get(_assignment_key(campaign, a, ordered), "")
            for a in post_assignments
        ]
        need_gen = [i for i, b in enumerate(variation_bodies) if not b]
        if not generate:
            for i in need_gen:
                variation_bodies[i] = post_assignments[i].body or ""
        elif need_gen:
            seed = campaign.seed_content or campaign.raw_brief or campaign.title
            # Group the not-yet-filled posters by team persona so each author's
            # post is written in that team's voice, one gateway call per persona.
            by_persona: dict[str, list[int]] = {}
            for idx in need_gen:
                key = persona_by_user.get(post_assignments[idx].user_id, "")
                by_persona.setdefault(key, []).append(idx)
            for persona, idxs in by_persona.items():
                bodies = await generate_variations(
                    seed,
                    len(idxs),
                    tone=campaign.tone,
                    length=campaign.length,
                    language=campaign.language,
                    extra=effective_rules,
                    persona=persona or None,
                )
                for pos, idx in enumerate(idxs):
                    variation_bodies[idx] = bodies[pos] if pos < len(bodies) else ""

    rows: list[Post] = []

    # Create the poster (variation) rows first; remember them by slot index.
    # The key is derived from each row's own uuid so a rebuild that retains
    # already-published rows can never collide with a prior plan's keys.
    poster_rows: list[Post] = []
    for idx, a in enumerate(post_assignments):
        row_id = uuid.uuid4()
        row = Post(
            id=row_id,
            campaign_id=campaign_id,
            user_id=a.user_id,
            social_account_id=account_by_user.get(a.user_id),
            action="post",
            body=(
                variation_bodies[idx] if idx < len(variation_bodies) else (a.body or "")
            ),
            angle=a.angle,
            lang=campaign.language,
            link=campaign.link,
            image_url=campaign.image_url,
            image_asset_id=campaign.image_asset_id,
            image_alt=campaign.image_alt,
            status="pending",
            idempotency_key=f"{campaign_id}:post:{a.user_id}:{row_id}",
        )
        poster_rows.append(row)
        rows.append(row)

    preserved_interactions: list[str | None] = [
        preserved.get(_assignment_key(campaign, a, ordered)) or None
        for a in interaction_assignments
    ]
    interaction_texts = await _resolve_interaction_texts(
        campaign,
        interaction_assignments,
        poster_rows,
        persona_by_user,
        generate=generate,
        extra=effective_rules,
        preserved=preserved_interactions,
    )

    for i, a in enumerate(interaction_assignments):
        target_post_id, target_external_id = _resolve_interaction_target(
            campaign, a, poster_rows
        )
        row_id = uuid.uuid4()
        row = Post(
            id=row_id,
            campaign_id=campaign_id,
            user_id=a.user_id,
            social_account_id=account_by_user.get(a.user_id),
            action=a.action,
            body=interaction_texts[i] if i < len(interaction_texts) else (a.body or ""),
            angle=a.angle,
            lang=campaign.language,
            target_post_id=target_post_id,
            target_external_id=target_external_id,
            status="pending",
            idempotency_key=f"{campaign_id}:{a.action}:{a.user_id}:{row_id}",
        )
        rows.append(row)

    # Self-comment ("link in the comments"): the author's own follow-up comment
    # on their own post, a short while after it publishes. Modeled as its own
    # tracked row (targeting the poster row) so it is visible in the plan and,
    # when the socialActions API is unavailable, falls back to the same
    # assisted-manual step as likes and comments instead of failing silently.
    if campaign.self_comment:
        for poster in poster_rows:
            sc_id = uuid.uuid4()
            rows.append(
                Post(
                    id=sc_id,
                    campaign_id=campaign_id,
                    user_id=poster.user_id,
                    social_account_id=poster.social_account_id,
                    action="self_comment",
                    body=campaign.self_comment,
                    lang=campaign.language,
                    target_post_id=poster.id,
                    status="pending",
                    idempotency_key=(
                        f"{campaign_id}:self_comment:{poster.user_id}:{sc_id}"
                    ),
                )
            )

    await post_repo.bulk_create(db, rows)

    # draft -> review (manual plan) or generating -> review (LLM job); both legal.
    if campaign.status != "review":
        await transition(db, campaign, "review", actor_id=actor_id)

    await audit_repo.record(
        db,
        actor_id=actor_id,
        action="campaign_plan_built",
        campaign_id=campaign_id,
        detail={"posts": len(rows), "generated": generate},
    )
    return rows


async def check_completion(db: AsyncSession, campaign_id: uuid.UUID) -> None:
    """Move a publishing campaign to completed once every post is terminal."""
    campaign = await campaign_repo.get(db, campaign_id)
    if campaign is None or campaign.status != "publishing":
        return
    if await post_repo.all_terminal(db, campaign_id):
        await transition(db, campaign, "completed")
