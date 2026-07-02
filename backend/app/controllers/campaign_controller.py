"""Campaign controller: request handling and authorization.

Controllers call repositories and services and return schema objects, and enforce
the fine-grained authorization the route-level role gate cannot.
"""

import uuid
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.deps import ROLE_HIERARCHY
from app.core.engagement import is_assisted
from app.core.linkedin_urn import resolve_post_urn
from app.models.campaign import Campaign
from app.models.user import User
from app.repositories import audit_repo
from app.repositories.campaign_repo import campaign_repo
from app.repositories.post_repo import post_repo
from app.repositories.social_account_repo import social_account_repo
from app.schemas.campaign import (
    ApprovalReadiness,
    CampaignCreate,
    CampaignDetail,
    CampaignOut,
    CampaignUpdate,
)
from app.schemas.common import Page, PageParams
from app.schemas.post import PlanRequest, PostOut
from app.services import campaign_service
from app.services.campaign_service import TransitionError
from app.workers import queue


def _is_editor(user: User) -> bool:
    return ROLE_HIERARCHY.get(user.role, -1) >= ROLE_HIERARCHY["editor"]


def _is_admin(user: User) -> bool:
    return user.role == "admin"


def _require_type_permission(campaign_type: str, user: User) -> None:
    """Distribute is editor+; amplify is open to any role."""
    if campaign_type == "distribute" and not _is_editor(user):
        raise HTTPException(403, "Distribute campaigns require the editor role.")


def _require_source_material(
    campaign_type: str, *, seed_url: str | None, seed_content: str | None
) -> None:
    """Every campaign is generated, so it cannot exist without source material.

    Amplify acts on one specific post, so it needs both the post URL (the target
    of the likes, comments, and reshares) and the post text (what the AI writes
    those comments and reshares from, since we cannot read the text from the URL).
    Distribute turns the seed text into per-member posts, so that text is
    required; its URL is only an optional reference.
    """
    has_url = bool(seed_url and seed_url.strip())
    has_text = bool(seed_content and seed_content.strip())
    if campaign_type == "amplify":
        if not has_url:
            raise HTTPException(422, "The post URL to amplify is required.")
        if not has_text:
            raise HTTPException(
                422,
                "Paste the post text: the AI writes comments and reshares from it.",
            )
    elif not has_text:
        raise HTTPException(
            422, "Seed text is required so the AI can generate the posts."
        )


def _require_resolvable_amplify_target(
    campaign_type: str, *, seed_url: str | None, seed_urn: str | None
) -> None:
    """Amplify acts on one live post, so its URL must parse to an activity URN.

    ``_require_source_material`` only checks the URL is present; a string like
    "test" passes that but resolves to no URN, leaving every like, comment, and
    reshare with a null target that fails at launch. Reject it up front so a
    doomed campaign is never created.
    """
    if campaign_type == "amplify" and (seed_url and seed_url.strip()) and not seed_urn:
        raise HTTPException(
            422,
            "That post URL could not be read as a LinkedIn post. Paste the full "
            "post URL (the one with an activity id) or a lnkd.in share link.",
        )


async def _load_or_404(db: AsyncSession, campaign_id: uuid.UUID) -> Campaign:
    campaign = await campaign_repo.get(db, campaign_id)
    if campaign is None:
        raise HTTPException(404, "Campaign not found.")
    return campaign


async def _can_view(db: AsyncSession, campaign: Campaign, user: User) -> bool:
    if _is_admin(user) or campaign.created_by == user.id:
        return True
    posts = await post_repo.list_for_campaign(db, campaign.id)
    return any(p.user_id == user.id for p in posts)


async def list_campaigns(
    db: AsyncSession, params: PageParams, user: User
) -> Page[CampaignOut]:
    page = await campaign_repo.paginate_for_user(
        db, params=params, user_id=user.id, is_admin=_is_admin(user)
    )
    return Page[CampaignOut](
        items=[CampaignOut.model_validate(c) for c in page.items],
        next_cursor=page.next_cursor,
    )


async def create_campaign(
    db: AsyncSession, body: CampaignCreate, actor: User
) -> CampaignOut:
    _require_type_permission(body.type, actor)
    _require_source_material(
        body.type, seed_url=body.seed_url, seed_content=body.seed_content
    )
    seed_urn = await resolve_post_urn(body.seed_url)
    _require_resolvable_amplify_target(
        body.type, seed_url=body.seed_url, seed_urn=seed_urn
    )
    campaign = await campaign_repo.create(
        db,
        title=body.title,
        type=body.type,
        raw_brief=body.raw_brief,
        seed_url=body.seed_url,
        seed_urn=seed_urn,
        seed_content=body.seed_content,
        tone=body.tone,
        length=body.length,
        language=body.language,
        extra_instructions=body.extra_instructions,
        image_url=body.image_url,
        image_asset_id=body.image_asset_id,
        image_alt=body.image_alt,
        link=body.link,
        link_placement=body.link_placement,
        self_comment=body.self_comment,
        stagger_min_seconds=body.stagger_min_seconds,
        stagger_max_seconds=body.stagger_max_seconds,
        status="draft",
        created_by=actor.id,
    )
    await audit_repo.record(
        db,
        actor_id=actor.id,
        action="campaign_created",
        campaign_id=campaign.id,
        detail={"type": body.type, "title": body.title},
    )
    await db.commit()
    await db.refresh(campaign)
    return CampaignOut.model_validate(campaign)


async def get_campaign(
    db: AsyncSession, campaign_id: uuid.UUID, user: User
) -> CampaignDetail:
    campaign = await _load_or_404(db, campaign_id)
    if not await _can_view(db, campaign, user):
        raise HTTPException(403, "You do not have access to this campaign.")
    counts = await campaign_repo.count_by_status(db, campaign_id)
    detail = CampaignDetail.model_validate(campaign)
    detail.counts = counts
    detail.post_count = sum(counts.values())
    return detail


async def approval_readiness(
    db: AsyncSession, campaign_id: uuid.UUID, user: User
) -> ApprovalReadiness:
    """Pre-flight: can this user approve their posts here, or reconnect first?

    Mirrors the approve gate exactly (same assisted rule and reconnect buffer) so
    the UI can prompt for re-consent up front instead of failing mid-approval.
    Assisted-manual posts (comments and likes done by hand) need no token, so a
    user with only those never sees a reconnect prompt.
    """
    campaign = await _load_or_404(db, campaign_id)
    if not await _can_view(db, campaign, user):
        raise HTTPException(403, "You do not have access to this campaign.")

    pending = await post_repo.list_pending_for_campaign_user(db, campaign_id, user.id)
    requires_linkedin = any(not is_assisted(p.action) for p in pending)

    account = await social_account_repo.get_by_user(db, user.id)
    connected = account is not None
    needs_reconnect = requires_linkedin and (
        account is None
        or account.requires_reconnect(
            now=datetime.now(UTC),
            buffer_hours=settings.LINKEDIN_RECONNECT_BUFFER_HOURS,
        )
    )
    return ApprovalReadiness(
        pending_count=len(pending),
        requires_linkedin=requires_linkedin,
        connected=connected,
        needs_reconnect=needs_reconnect,
    )


async def update_campaign(
    db: AsyncSession, campaign_id: uuid.UUID, body: CampaignUpdate, actor: User
) -> CampaignOut:
    campaign = await _load_or_404(db, campaign_id)
    if not (_is_admin(actor) or campaign.created_by == actor.id):
        raise HTTPException(403, "Only the creator or an admin can edit a campaign.")
    if campaign.status not in ("draft", "review"):
        raise HTTPException(409, "Campaign can only be edited before it is launched.")

    updates = body.model_dump(exclude_unset=True)
    if "seed_url" in updates:
        updates["seed_urn"] = await resolve_post_urn(updates["seed_url"])
    # The type is locked on edit; validate the effective (merged) source material
    # so a campaign can never be saved into a state that cannot generate anything.
    _require_source_material(
        campaign.type,
        seed_url=updates.get("seed_url", campaign.seed_url),
        seed_content=updates.get("seed_content", campaign.seed_content),
    )
    _require_resolvable_amplify_target(
        campaign.type,
        seed_url=updates.get("seed_url", campaign.seed_url),
        seed_urn=updates.get("seed_urn", campaign.seed_urn),
    )
    if updates:
        await campaign_repo.update(db, campaign, **updates)
        # JSON-safe detail for the audit_log JSONB: model_dump(mode="json")
        # renders UUIDs (e.g. image_asset_id) and datetimes as strings, which the
        # raw `updates` dict does not. seed_content is dropped (bulky, not useful
        # in the log); the seed_urn we derived above is already a string.
        detail = body.model_dump(exclude_unset=True, mode="json")
        detail.pop("seed_content", None)
        if "seed_urn" in updates:
            detail["seed_urn"] = updates["seed_urn"]
        await audit_repo.record(
            db,
            actor_id=actor.id,
            action="campaign_updated",
            campaign_id=campaign_id,
            detail=detail,
        )
        await db.commit()
        await db.refresh(campaign)
    return CampaignOut.model_validate(campaign)


_DELETABLE_STATUSES = ("draft", "review", "failed")


async def delete_campaign(
    db: AsyncSession, campaign_id: uuid.UUID, actor: User
) -> None:
    campaign = await _load_or_404(db, campaign_id)
    if not (_is_admin(actor) or campaign.created_by == actor.id):
        raise HTTPException(403, "Only the creator or an admin can delete a campaign.")
    # In production a launched campaign has live or in-flight posts, so a plain
    # creator can only delete it before launch. Admins may delete in any state
    # (cleanup, pilot resets); deletion cancels any still-queued jobs so nothing
    # from the removed campaign publishes afterward. In local/dev anyone may
    # delete in any state to make test campaigns easy to clear.
    if (
        settings.is_production
        and not _is_admin(actor)
        and campaign.status not in _DELETABLE_STATUSES
    ):
        raise HTTPException(409, "Only un-launched campaigns can be deleted.")
    await campaign_service.delete_campaign(db, campaign, actor_id=actor.id)
    await db.commit()


async def build_plan(
    db: AsyncSession, campaign_id: uuid.UUID, body: PlanRequest, actor: User
) -> list[PostOut]:
    """Create posts from the participant list (no LLM)."""
    campaign = await _load_or_404(db, campaign_id)
    _require_type_permission(campaign.type, actor)
    if not (_is_admin(actor) or campaign.created_by == actor.id):
        raise HTTPException(403, "Only the creator or an admin can plan a campaign.")
    assignments = await campaign_service.expand_participants(
        db,
        campaign,
        body.participant_ids,
        actions_by_participant=body.actions_by_participant,
    )
    rows = await campaign_service.build_plan(
        db,
        campaign_id,
        assignments,
        generate=False,
        regenerate=body.regenerate,
        actor_id=actor.id,
    )
    await db.commit()
    return [PostOut.model_validate(r) for r in rows]


async def generate(
    db: AsyncSession, campaign_id: uuid.UUID, body: PlanRequest, actor: User
) -> CampaignOut:
    """Enqueue LLM generation for the participant plan; returns the campaign."""
    campaign = await _load_or_404(db, campaign_id)
    _require_type_permission(campaign.type, actor)
    if not (_is_admin(actor) or campaign.created_by == actor.id):
        raise HTTPException(403, "Only the creator or an admin can generate.")
    assignments = await campaign_service.expand_participants(
        db,
        campaign,
        body.participant_ids,
        actions_by_participant=body.actions_by_participant,
    )
    try:
        await campaign_service.transition(db, campaign, "generating", actor_id=actor.id)
    except TransitionError as exc:
        raise HTTPException(409, str(exc)) from exc
    await db.commit()

    await queue.enqueue_job(
        "generate_drafts",
        str(campaign_id),
        [a.model_dump(mode="json") for a in assignments],
        regenerate=body.regenerate,
    )
    await db.refresh(campaign)
    return CampaignOut.model_validate(campaign)


async def launch(db: AsyncSession, campaign_id: uuid.UUID, actor: User) -> CampaignOut:
    campaign = await _load_or_404(db, campaign_id)
    if not (_is_admin(actor) or campaign.created_by == actor.id):
        raise HTTPException(403, "Only the creator or an admin can launch.")
    if campaign.status != "review":
        raise HTTPException(409, "Campaign must be in review to launch.")

    from datetime import UTC, datetime

    campaign.launched_by = actor.id
    campaign.launched_at = datetime.now(UTC)
    await audit_repo.record(
        db, actor_id=actor.id, action="campaign_launched", campaign_id=campaign_id
    )
    await db.commit()

    await queue.enqueue_job("launch_campaign", str(campaign_id))
    await db.refresh(campaign)
    return CampaignOut.model_validate(campaign)


async def pause(db: AsyncSession, campaign_id: uuid.UUID, actor: User) -> CampaignOut:
    """Pause a launched campaign so no further posts publish or DMs go out.

    Deferred worker jobs (staggered notifies, backoff republishes, reminders)
    check the campaign status when they fire and abort while it is paused, so
    pausing effectively drains the remaining queue. Resume re-drives the work.
    """
    campaign = await _load_or_404(db, campaign_id)
    if not (_is_admin(actor) or campaign.created_by == actor.id):
        raise HTTPException(403, "Only the creator or an admin can pause a campaign.")
    try:
        await campaign_service.transition(db, campaign, "paused", actor_id=actor.id)
    except TransitionError:
        raise HTTPException(409, "Only a launched campaign can be paused.") from None
    await db.commit()
    await db.refresh(campaign)
    return CampaignOut.model_validate(campaign)


async def resume(db: AsyncSession, campaign_id: uuid.UUID, actor: User) -> CampaignOut:
    """Resume a paused campaign and re-enqueue its outstanding work."""
    campaign = await _load_or_404(db, campaign_id)
    if not (_is_admin(actor) or campaign.created_by == actor.id):
        raise HTTPException(403, "Only the creator or an admin can resume a campaign.")
    try:
        await campaign_service.transition(db, campaign, "publishing", actor_id=actor.id)
    except TransitionError:
        raise HTTPException(409, "Only a paused campaign can be resumed.") from None
    await db.commit()

    await queue.enqueue_job("resume_campaign", str(campaign_id))
    await db.refresh(campaign)
    return CampaignOut.model_validate(campaign)
