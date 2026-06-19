"""Auth controller: Google login completion (domain check, upsert, JWT mint)."""

from fastapi import HTTPException
from fastapi_sso.sso.base import OpenID
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.security import create_access_token
from app.repositories.user_repo import user_repo
from app.schemas.auth import TokenResponse


async def complete_google_login(db: AsyncSession, sso_user: OpenID) -> TokenResponse:
    email = sso_user.email
    if not email:
        raise HTTPException(status_code=400, detail="No email received from Google.")

    domain = email.split("@")[-1].lower()
    if domain != settings.COMPANY_EMAIL_DOMAIN.lower():
        raise HTTPException(
            status_code=403, detail="Use your company account to sign in."
        )

    user = await user_repo.get_by_email(db, email=email)
    if user is None:
        role = "admin" if email.lower() in settings.bootstrap_admin_emails else "viewer"
        user = await user_repo.create(
            db,
            email=email.lower(),
            name=sso_user.display_name,
            avatar_url=sso_user.picture,
            google_sub=sso_user.id,
            role=role,
        )
        await db.commit()
        await db.refresh(user)
    else:
        changed = False
        if sso_user.display_name and user.name != sso_user.display_name:
            user.name = sso_user.display_name
            changed = True
        if sso_user.picture and user.avatar_url != sso_user.picture:
            user.avatar_url = sso_user.picture
            changed = True
        if sso_user.id and not user.google_sub:
            user.google_sub = sso_user.id
            changed = True
        if changed:
            await db.commit()
            await db.refresh(user)

    if not user.is_active:
        raise HTTPException(status_code=403, detail="This account is disabled.")

    token = await create_access_token(user_id=user.id, email=user.email, role=user.role)
    return TokenResponse(access_token=token)
