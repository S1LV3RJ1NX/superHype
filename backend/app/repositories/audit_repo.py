"""Audit log repository: append-only recording of externally triggered mutations."""

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog


async def record(
    db: AsyncSession,
    *,
    actor_id: uuid.UUID,
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
