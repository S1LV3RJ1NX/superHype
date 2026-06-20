"""Controller for LinkedIn connection management.

Authorize, complete, and disconnect with Redis-bound CSRF state. The authorize
state can optionally carry a pending action (resume_post_id) so re-consent
resumes the original approve in one flow (reconnect-then-act).
"""

import json
import secrets
import uuid

import httpx
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import crypto
from app.core.redis import get_redis
from app.models.user import User
from app.repositories.audit_repo import record as audit_record
from app.repositories.post_repo import post_repo
from app.repositories.social_account_repo import social_account_repo
from app.schemas.connection import AuthorizeUrlOut, ConnectionOut
from app.services import linkedin_oauth_service
from app.workers import queue

_KEY_PREFIX = "super-hype:"
_STATE_TTL_SECONDS = 600  # 10 minutes


async def authorize_linkedin(
    user: User, resume_post_id: uuid.UUID | None = None
) -> AuthorizeUrlOut:
    """Generate a CSRF state, store in Redis, and return the authorize URL.

    The state is bound to the user and, optionally, to a pending post so the
    callback can resume the approve that triggered the reconnect.
    """
    state = secrets.token_urlsafe(32)
    payload = {
        "user_id": str(user.id),
        "resume_post_id": str(resume_post_id) if resume_post_id else None,
    }
    redis = await get_redis()
    await redis.set(
        f"{_KEY_PREFIX}li:state:{state}", json.dumps(payload), ex=_STATE_TTL_SECONDS
    )
    url = linkedin_oauth_service.authorize_url(state)
    return AuthorizeUrlOut(authorize_url=url)


def _parse_state(raw: str | bytes | None, user: User) -> uuid.UUID | None:
    """Validate stored state belongs to the user; return any resume target."""
    if raw is None:
        raise HTTPException(400, "Invalid or expired connection request.")
    if isinstance(raw, bytes):
        raw = raw.decode()
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        data = None
    if not isinstance(data, dict):
        # Tolerate the legacy format where the value was the bare user id.
        data = {"user_id": raw, "resume_post_id": None}
    if data.get("user_id") != str(user.id):
        raise HTTPException(400, "Invalid or expired connection request.")
    rid = data.get("resume_post_id")
    return uuid.UUID(rid) if rid else None


async def complete_linkedin(
    db: AsyncSession,
    user: User,
    code: str,
    state: str,
) -> ConnectionOut:
    """Validate state, exchange code, upsert the account, and resume any action."""
    redis = await get_redis()
    key = f"{_KEY_PREFIX}li:state:{state}"
    raw = await redis.get(key)
    resume_post_id = _parse_state(raw, user)
    await redis.delete(key)

    try:
        tokens = await linkedin_oauth_service.exchange_code(code)
        urn, display_name = await linkedin_oauth_service.fetch_identity(
            tokens.access_token
        )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=400,
            detail="LinkedIn connection failed. The code may have expired or been reused.",
        ) from exc

    account = await social_account_repo.upsert(
        db,
        user_id=user.id,
        platform="linkedin",
        external_urn=urn,
        display_name=display_name,
        access_token_enc=crypto.encrypt(tokens.access_token),
        refresh_token_enc=(
            crypto.encrypt(tokens.refresh_token) if tokens.refresh_token else None
        ),
        scopes=tokens.scopes,
        expires_at=tokens.expires_at,
        status="active",
    )
    await audit_record(
        db, actor_id=user.id, action="linkedin_connected", detail={"urn": urn}
    )

    # Reconnect-then-act: resume the approve that sent the user here. Idempotent,
    # owner-checked, and a no-op if the post is gone or no longer pending.
    resumed_post = None
    if resume_post_id is not None:
        post = await post_repo.get(db, resume_post_id)
        if (
            post is not None
            and post.user_id == user.id
            and post.status in ("pending", "scheduled")
        ):
            post.status = "approved"
            # Link the freshly connected account if the post was planned before
            # the owner connected, so the worker can resolve a live token.
            if post.social_account_id is None:
                post.social_account_id = account.id
            await audit_record(
                db,
                actor_id=user.id,
                action="post_approved",
                campaign_id=post.campaign_id,
                post_id=post.id,
            )
            resumed_post = post

    await db.commit()

    result = ConnectionOut.model_validate(account)
    if resumed_post is not None:
        await queue.enqueue_job("publish_post", str(resumed_post.id))
        result.resumed_post_id = resumed_post.id
        result.resumed_campaign_id = resumed_post.campaign_id
    return result


async def disconnect_linkedin(db: AsyncSession, user: User) -> None:
    """Revoke (best effort) and delete the LinkedIn connection."""
    account = await social_account_repo.get_by_user(db, user.id, platform="linkedin")
    if account is None:
        return
    token = crypto.decrypt(account.access_token_enc)
    await linkedin_oauth_service.revoke(token)
    await social_account_repo.delete(db, account)
    await audit_record(db, actor_id=user.id, action="linkedin_disconnected")
    await db.commit()
