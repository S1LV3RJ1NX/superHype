"""Campaigns router. Thin: declares deps, parses params/bodies, calls controllers.

Create is open to any authed user; the controller gates distribute to editor+.
Launch is gated to the creator or an admin. There is no admin campaign sign-off.
"""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.controllers import campaign_controller
from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.campaign import (
    ApprovalReadiness,
    CampaignCreate,
    CampaignDetail,
    CampaignOut,
    CampaignUpdate,
)
from app.schemas.common import Page, PageParams
from app.schemas.post import PlanRequest, PostOut

router = APIRouter(prefix="/v1/campaigns", tags=["campaigns"])


@router.get("", response_model=Page[CampaignOut])
async def list_campaigns(
    params: PageParams = Depends(),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Page[CampaignOut]:
    return await campaign_controller.list_campaigns(db, params, user)


@router.post("", response_model=CampaignOut, status_code=201)
async def create_campaign(
    body: CampaignCreate,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> CampaignOut:
    return await campaign_controller.create_campaign(db, body, actor)


@router.get("/{campaign_id}", response_model=CampaignDetail)
async def get_campaign(
    campaign_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CampaignDetail:
    return await campaign_controller.get_campaign(db, campaign_id, user)


@router.get("/{campaign_id}/approval-readiness", response_model=ApprovalReadiness)
async def approval_readiness(
    campaign_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ApprovalReadiness:
    return await campaign_controller.approval_readiness(db, campaign_id, user)


@router.patch("/{campaign_id}", response_model=CampaignOut)
async def update_campaign(
    campaign_id: uuid.UUID,
    body: CampaignUpdate,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> CampaignOut:
    return await campaign_controller.update_campaign(db, campaign_id, body, actor)


@router.delete("/{campaign_id}", status_code=204)
async def delete_campaign(
    campaign_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> None:
    await campaign_controller.delete_campaign(db, campaign_id, actor)


@router.post("/{campaign_id}/plan", response_model=list[PostOut])
async def build_plan(
    campaign_id: uuid.UUID,
    body: PlanRequest,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> list[PostOut]:
    return await campaign_controller.build_plan(db, campaign_id, body, actor)


@router.post("/{campaign_id}/generate", response_model=CampaignOut)
async def generate(
    campaign_id: uuid.UUID,
    body: PlanRequest,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> CampaignOut:
    return await campaign_controller.generate(db, campaign_id, body, actor)


@router.post("/{campaign_id}/launch", response_model=CampaignOut)
async def launch(
    campaign_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> CampaignOut:
    return await campaign_controller.launch(db, campaign_id, actor)


@router.post("/{campaign_id}/reset", response_model=CampaignOut)
async def reset(
    campaign_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> CampaignOut:
    return await campaign_controller.reset(db, campaign_id, actor)


@router.post("/{campaign_id}/pause", response_model=CampaignOut)
async def pause(
    campaign_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> CampaignOut:
    return await campaign_controller.pause(db, campaign_id, actor)


@router.post("/{campaign_id}/resume", response_model=CampaignOut)
async def resume(
    campaign_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> CampaignOut:
    return await campaign_controller.resume(db, campaign_id, actor)
