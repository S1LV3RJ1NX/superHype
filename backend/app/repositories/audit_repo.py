"""Audit log repository: append-only recording of externally triggered mutations."""

import uuid
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog
from app.models.post import Post


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


async def detach_pending_posts(db: AsyncSession, campaign_id: uuid.UUID) -> None:
    """Null audit_log.post_id for a campaign's pending posts before a rebuild.

    A rebuild (build_plan) hard-deletes the pending post rows. After a reset those
    rows can still be referenced by audit_log entries from the previous run
    (fk_audit_log_post_id_posts; post_id is nullable), which otherwise blocks the
    delete. Detach only the pending posts so the rebuild succeeds while the audit
    trail stays, still linked to the campaign.
    """
    pending = select(Post.id).where(
        Post.campaign_id == campaign_id, Post.status == "pending"
    )
    await db.execute(
        update(AuditLog).where(AuditLog.post_id.in_(pending)).values(post_id=None)
    )
    await db.flush()


async def delete_for_campaign(db: AsyncSession, campaign_id: uuid.UUID) -> None:
    """Remove audit rows tied to a campaign so the campaign can be deleted.

    Post-level audits also carry `campaign_id`, so this clears their `post_id`
    references too, letting the campaign's posts be deleted without FK errors.
    """
    await db.execute(delete(AuditLog).where(AuditLog.campaign_id == campaign_id))
    await db.flush()
