"""Campaign controller: request handling and authorization.

Controllers call repositories and services and return schema objects, and enforce
the fine-grained authorization the route-level role gate cannot.
"""

import uuid

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import ROLE_HIERARCHY
from app.core.linkedin_urn import parse_post_urn
from app.models.campaign import Campaign
from app.models.user import User
from app.repositories import audit_repo
from app.repositories.campaign_repo import campaign_repo
from app.repositories.post_repo import post_repo
from app.schemas.campaign import (
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
    campaign = await campaign_repo.create(
        db,
        title=body.title,
        type=body.type,
        raw_brief=body.raw_brief,
        seed_url=body.seed_url,
        seed_urn=parse_post_urn(body.seed_url),
        seed_content=body.seed_content,
        tone=body.tone,
        length=body.length,
        language=body.language,
        extra_instructions=body.extra_instructions,
        image_url=body.image_url,
        image_alt=body.image_alt,
        link=body.link,
        link_placement=body.link_placement,
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
        updates["seed_urn"] = parse_post_urn(updates["seed_url"])
    if updates:
        await campaign_repo.update(db, campaign, **updates)
        await audit_repo.record(
            db,
            actor_id=actor.id,
            action="campaign_updated",
            campaign_id=campaign_id,
            detail={k: v for k, v in updates.items() if k != "seed_content"},
        )
        await db.commit()
        await db.refresh(campaign)
    return CampaignOut.model_validate(campaign)


async def build_plan(
    db: AsyncSession, campaign_id: uuid.UUID, body: PlanRequest, actor: User
) -> list[PostOut]:
    """Create posts from a manual assignment plan (no LLM)."""
    campaign = await _load_or_404(db, campaign_id)
    _require_type_permission(campaign.type, actor)
    if not (_is_admin(actor) or campaign.created_by == actor.id):
        raise HTTPException(403, "Only the creator or an admin can plan a campaign.")
    rows = await campaign_service.build_plan(
        db, campaign_id, body.assignments, generate=False, actor_id=actor.id
    )
    await db.commit()
    return [PostOut.model_validate(r) for r in rows]


async def generate(
    db: AsyncSession, campaign_id: uuid.UUID, body: PlanRequest, actor: User
) -> CampaignOut:
    """Enqueue LLM generation for the assignment plan; returns the campaign."""
    campaign = await _load_or_404(db, campaign_id)
    _require_type_permission(campaign.type, actor)
    if not (_is_admin(actor) or campaign.created_by == actor.id):
        raise HTTPException(403, "Only the creator or an admin can generate.")
    try:
        await campaign_service.transition(db, campaign, "generating", actor_id=actor.id)
    except TransitionError as exc:
        raise HTTPException(409, str(exc)) from exc
    await db.commit()

    await queue.enqueue_job(
        "generate_drafts",
        str(campaign_id),
        [a.model_dump(mode="json") for a in body.assignments],
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
