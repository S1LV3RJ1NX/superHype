"""Controller for LinkedIn connection management.

Authorize, complete, and disconnect with Redis-bound CSRF state.
"""

import secrets

import httpx
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import crypto
from app.core.redis import get_redis
from app.models.user import User
from app.repositories.audit_repo import record as audit_record
from app.repositories.social_account_repo import social_account_repo
from app.schemas.connection import AuthorizeUrlOut, ConnectionOut
from app.services import linkedin_oauth_service

_KEY_PREFIX = "super-hype:"
_STATE_TTL_SECONDS = 600  # 10 minutes


async def authorize_linkedin(user: User) -> AuthorizeUrlOut:
    """Generate a CSRF state, store in Redis, and return the authorize URL."""
    state = secrets.token_urlsafe(32)
    redis = await get_redis()
    await redis.set(
        f"{_KEY_PREFIX}li:state:{state}", str(user.id), ex=_STATE_TTL_SECONDS
    )
    url = linkedin_oauth_service.authorize_url(state)
    return AuthorizeUrlOut(authorize_url=url)


async def complete_linkedin(
    db: AsyncSession,
    user: User,
    code: str,
    state: str,
) -> ConnectionOut:
    """Validate state, exchange code, encrypt tokens, upsert the account."""
    redis = await get_redis()
    key = f"{_KEY_PREFIX}li:state:{state}"
    owner = await redis.get(key)
    if owner is None or owner != str(user.id):
        raise HTTPException(400, "Invalid or expired connection request.")
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
    await db.commit()
    return ConnectionOut.model_validate(account)


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
