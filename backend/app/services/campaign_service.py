"""Campaign service: state machine, plan building, and completion.

Owns the campaign status transitions and the translation of an assignment plan
into post rows (with optional LLM fill). Repositories do the DB access; this
layer owns the multi-step logic and writes audit rows.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.logger import get_logger
from app.models.campaign import Campaign
from app.models.post import Post
from app.repositories import audit_repo
from app.repositories.campaign_repo import campaign_repo
from app.repositories.post_repo import post_repo
from app.repositories.social_account_repo import social_account_repo
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
    "completed": set(),
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

    # Variation bodies for distribute posters.
    variation_bodies: list[str] = []
    if post_assignments:
        if generate:
            variation_bodies = await generate_variations(
                campaign.seed_content or campaign.raw_brief or campaign.title,
                len(post_assignments),
                tone=campaign.tone,
                length=campaign.length,
                language=campaign.language,
                extra=campaign.extra_instructions,
            )
        else:
            variation_bodies = [a.body or "" for a in post_assignments]

    # Interaction text (LLM only; manual text comes straight off the assignment).
    interaction_texts: list[str] = []
    if interaction_assignments:
        if generate:
            target_text = campaign.seed_content or campaign.title
            interaction_texts = await generate_interactions(
                target_text,
                [
                    {"action": a.action, "angle": a.angle or ""}
                    for a in interaction_assignments
                ],
                tone=campaign.tone,
                length=campaign.length,
                language=campaign.language,
                extra=campaign.extra_instructions,
            )
        else:
            interaction_texts = [a.body or "" for a in interaction_assignments]

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
            image_alt=campaign.image_alt,
            status="pending",
            idempotency_key=f"{campaign_id}:post:{a.user_id}:{row_id}",
        )
        poster_rows.append(row)
        rows.append(row)

    for i, a in enumerate(interaction_assignments):
        target_post_id: uuid.UUID | None = None
        target_external_id: str | None = None
        if campaign.type == "distribute" and poster_rows:
            slot = a.target_post_index if a.target_post_index is not None else 0
            slot = max(0, min(slot, len(poster_rows) - 1))
            target_post_id = poster_rows[slot].id
        else:
            target_external_id = campaign.seed_urn

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
