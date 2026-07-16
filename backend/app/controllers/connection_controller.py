"""Controller for social connection management (LinkedIn and X).

Authorize, complete, and disconnect with Redis-bound CSRF state. The authorize
state can optionally carry a pending action (resume_post_id) so re-consent
resumes the original approve in one flow (reconnect-then-act). The X state
additionally carries the PKCE code verifier, which never reaches the browser.
"""

import json
import secrets
import uuid
from datetime import UTC, datetime

import httpx
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core import crypto
from app.core.redis import get_redis
from app.models.post import Post
from app.models.social_account import SocialAccount
from app.models.user import User
from app.repositories.audit_repo import record as audit_record
from app.repositories.post_repo import post_repo
from app.repositories.social_account_repo import social_account_repo
from app.schemas.connection import AuthorizeUrlOut, ConnectionOut
from app.services import linkedin_oauth_service, x_oauth_service
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


async def authorize_x(
    user: User, resume_post_id: uuid.UUID | None = None
) -> AuthorizeUrlOut:
    """Generate CSRF state plus a PKCE pair, store both in Redis, and return the
    X authorize URL.

    The code verifier stays server-side (bound to the state) and is replayed at
    the code exchange; the browser only ever sees the S256 challenge.
    """
    if not settings.X_CLIENT_ID:
        raise HTTPException(503, "X is not configured on this deployment.")
    state = secrets.token_urlsafe(32)
    verifier, challenge = x_oauth_service.generate_pkce()
    payload = {
        "user_id": str(user.id),
        "resume_post_id": str(resume_post_id) if resume_post_id else None,
        "code_verifier": verifier,
    }
    redis = await get_redis()
    await redis.set(
        f"{_KEY_PREFIX}x:state:{state}", json.dumps(payload), ex=_STATE_TTL_SECONDS
    )
    url = x_oauth_service.authorize_url(state, challenge)
    return AuthorizeUrlOut(authorize_url=url)


def _reconnect_buffer_hours(platform: str) -> int:
    return (
        settings.X_RECONNECT_BUFFER_HOURS
        if platform == "x"
        else settings.LINKEDIN_RECONNECT_BUFFER_HOURS
    )


async def list_connections(db: AsyncSession, user: User) -> list[ConnectionOut]:
    """The user's social accounts, each flagged with its reconnect need.

    needs_reconnect is computed with the same buffer the approve gate uses, so the
    Connections page can prompt a reconnect for a token that is stale or merely
    expiring soon, not only one already marked stale.
    """
    accounts = await social_account_repo.list(db, user_id=user.id)
    now = datetime.now(UTC)
    out: list[ConnectionOut] = []
    for account in accounts:
        result = ConnectionOut.model_validate(account)
        result.needs_reconnect = account.requires_reconnect(
            now=now, buffer_hours=_reconnect_buffer_hours(account.platform)
        )
        out.append(result)
    return out


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


async def _resume_pending_post(
    db: AsyncSession,
    user: User,
    account: SocialAccount,
    resume_post_id: uuid.UUID | None,
) -> Post | None:
    """Reconnect-then-act: approve the post that triggered the reconnect.

    Idempotent, owner-checked, and a no-op if the post is gone or no longer
    pending. Returns the resumed post (uncommitted), or None.
    """
    if resume_post_id is None:
        return None
    post = await post_repo.get(db, resume_post_id)
    if (
        post is None
        or post.user_id != user.id
        # A LinkedIn post must never get approved (or linked) by an X connect
        # and vice versa: the worker routes by post.platform, so a mismatched
        # account would send one platform's token to the other's API.
        or post.platform != account.platform
        or post.status not in ("pending", "scheduled")
    ):
        return None
    post.status = "approved"
    # Link the freshly connected account if the post was planned before the
    # owner connected, so the worker can resolve a live token.
    if post.social_account_id is None:
        post.social_account_id = account.id
    await audit_record(
        db,
        actor_id=user.id,
        action="post_approved",
        campaign_id=post.campaign_id,
        post_id=post.id,
    )
    return post


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

    resumed_post = await _resume_pending_post(db, user, account, resume_post_id)
    await db.commit()

    result = ConnectionOut.model_validate(account)
    if resumed_post is not None:
        await queue.enqueue_job("publish_post", str(resumed_post.id))
        result.resumed_post_id = resumed_post.id
        result.resumed_campaign_id = resumed_post.campaign_id
    return result


async def complete_x(
    db: AsyncSession,
    user: User,
    code: str,
    state: str,
) -> ConnectionOut:
    """Validate state, replay the PKCE verifier in the code exchange, upsert the
    X account, and resume any pending action."""
    redis = await get_redis()
    key = f"{_KEY_PREFIX}x:state:{state}"
    raw = await redis.get(key)
    if raw is None:
        raise HTTPException(400, "Invalid or expired connection request.")
    if isinstance(raw, bytes):
        raw = raw.decode()
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        data = {}
    if not isinstance(data, dict) or data.get("user_id") != str(user.id):
        raise HTTPException(400, "Invalid or expired connection request.")
    await redis.delete(key)
    verifier = data.get("code_verifier") or ""
    rid = data.get("resume_post_id")
    resume_post_id = uuid.UUID(rid) if rid else None

    try:
        tokens = await x_oauth_service.exchange_code(code, verifier)
        x_user_id, display_name = await x_oauth_service.fetch_identity(
            tokens.access_token
        )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=400,
            detail="X connection failed. The code may have expired or been reused.",
        ) from exc

    account = await social_account_repo.upsert(
        db,
        user_id=user.id,
        platform="x",
        external_urn=x_user_id,
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
        db, actor_id=user.id, action="x_connected", detail={"x_user_id": x_user_id}
    )

    resumed_post = await _resume_pending_post(db, user, account, resume_post_id)
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


async def disconnect_x(db: AsyncSession, user: User) -> None:
    """Revoke (best effort) and delete the X connection."""
    account = await social_account_repo.get_by_user(db, user.id, platform="x")
    if account is None:
        return
    token = crypto.decrypt(account.access_token_enc)
    await x_oauth_service.revoke(token)
    await social_account_repo.delete(db, account)
    await audit_record(db, actor_id=user.id, action="x_disconnected")
    await db.commit()
