"""Audit log repository: append-only recording of externally triggered mutations."""

import uuid
from typing import Any

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog


async def record(
    db: AsyncSession,
    *,
    actor_id: uuid.UUID | None = None,
    action: str,
    detail: dict[str, Any] | None = None,
    campaign_id: uuid.UUID | None = None,
    post_id: uuid.UUID | None = None,
) -> AuditLog:
    entry = AuditLog(
        actor_id=actor_id,
        action=action,
        detail=detail,
        campaign_id=campaign_id,
        post_id=post_id,
    )
    db.add(entry)
    await db.flush()
    return entry


async def delete_for_campaign(db: AsyncSession, campaign_id: uuid.UUID) -> None:
    """Remove audit rows tied to a campaign so the campaign can be deleted.

    Post-level audits also carry `campaign_id`, so this clears their `post_id`
    references too, letting the campaign's posts be deleted without FK errors.
    """
    await db.execute(delete(AuditLog).where(AuditLog.campaign_id == campaign_id))
    await db.flush()
