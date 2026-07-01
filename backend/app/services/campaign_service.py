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


class TransitionError(Exception):
    """Raised when a campaign status transition is not allowed."""


# Legal campaign status transitions. No `approved` state: launch is gated per
# participant, not by an admin sign-off.
TRANSITIONS: dict[str, set[str]] = {
    "draft": {"generating", "review"},
    "generating": {"review", "failed"},
    "review": {"generating", "publishing"},
    "publishing": {"completed", "failed"},
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
) -> list[str]:
    """Produce one text per interaction, aligned to input order.

    When generating, comments and reshares are written from the body of the post
    they react to (the distribute variation, or the campaign seed text for
    amplify), and carry the actor's team persona. Interactions are grouped by
    their target text so each LLM call reasons about a single post.
    """
    if not interaction_assignments:
        return []
    if not generate:
        return [a.body or "" for a in interaction_assignments]

    def _target_text(a: Assignment) -> str:
        if campaign.type == "distribute" and poster_rows:
            slot = a.target_post_index if a.target_post_index is not None else 0
            slot = max(0, min(slot, len(poster_rows) - 1))
            body = poster_rows[slot].body or ""
            if body.strip():
                return body
        return campaign.seed_content or campaign.title or ""

    groups: dict[str, list[int]] = {}
    for idx, a in enumerate(interaction_assignments):
        groups.setdefault(_target_text(a), []).append(idx)

    texts: list[str] = ["" for _ in interaction_assignments]
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
            extra=campaign.extra_instructions,
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


async def expand_participants(
    db: AsyncSession, campaign: Campaign, participant_ids: list[uuid.UUID]
) -> list[Assignment]:
    """Turn a participant list into concrete actions from the campaign type.

    Amplify: every member likes, comments, and reposts the seed post. Distribute:
    every member authors their own post (its slot is their position in the list),
    then likes and comments on up to DISTRIBUTE_MAX_ENGAGEMENT_TARGETS other
    members' posts, founder-authored posts first, so a big campaign cannot fan out
    quadratically.
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
            out.append(Assignment(user_id=uid, action="like"))
            out.append(Assignment(user_id=uid, action="comment"))
            out.append(Assignment(user_id=uid, action="repost_comment"))
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


async def build_plan(
    db: AsyncSession,
    campaign_id: uuid.UUID,
    assignments: list[Assignment],
    *,
    generate: bool,
    actor_id: uuid.UUID | None = None,
) -> list[Post]:
    """Create post rows from an assignment plan, optionally filling text via LLM.

    Replaces only the pending posts so the call is safe to re-run; approved work
    awaiting publish (`scheduled`), published, failed, or skipped posts are never
    touched. Moves the campaign to `review`.
    """
    campaign = await campaign_repo.get(db, campaign_id)
    if campaign is None:
        raise TransitionError("Campaign not found.")

    await post_repo.delete_pending_for_campaign(db, campaign_id)

    post_assignments = [a for a in assignments if a.action == "post"]
    interaction_assignments = [a for a in assignments if a.action != "post"]

    # Resolve each participant's LinkedIn account once.
    account_by_user: dict[uuid.UUID, uuid.UUID | None] = {}
    for a in assignments:
        if a.user_id not in account_by_user:
            acct = await social_account_repo.get_by_user(db, a.user_id)
            account_by_user[a.user_id] = acct.id if acct else None

    # Team persona per acting user, so generated comments and reposts read in that
    # team's voice. Only needed when we actually call the LLM.
    persona_by_user: dict[uuid.UUID, str] = {}
    if generate:
        persona_by_user = await _personas_by_user(db, [a.user_id for a in assignments])

    # Variation bodies must be resolved before interactions: a distribute comment
    # is written from the body of the post it reacts to, so the poster rows have
    # to exist first. Manual text (generate=False) comes straight off the
    # assignment and never touches the gateway.
    if not post_assignments:
        variation_bodies: list[str] = []
    elif not generate:
        variation_bodies = [a.body or "" for a in post_assignments]
    else:
        seed = campaign.seed_content or campaign.raw_brief or campaign.title
        variation_bodies = ["" for _ in post_assignments]
        # Group posters by their team persona so each author's post is written in
        # that team's voice, batching one gateway call per distinct persona.
        by_persona: dict[str, list[int]] = {}
        for idx, a in enumerate(post_assignments):
            by_persona.setdefault(persona_by_user.get(a.user_id, ""), []).append(idx)
        for persona, idxs in by_persona.items():
            bodies = await generate_variations(
                seed,
                len(idxs),
                tone=campaign.tone,
                length=campaign.length,
                language=campaign.language,
                extra=campaign.extra_instructions,
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

    interaction_texts = await _resolve_interaction_texts(
        campaign,
        interaction_assignments,
        poster_rows,
        persona_by_user,
        generate=generate,
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
