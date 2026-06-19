"""Auth routes: Google OAuth login and callback."""

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi_sso.sso.google import GoogleSSO
from oauthlib.oauth2.rfc6749.errors import OAuth2Error as OAuthError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.controllers import auth_controller
from app.db.session import get_db
from app.schemas.auth import GoogleCallbackBody, TokenResponse

router = APIRouter(prefix="/v1/google", tags=["auth"])


def _get_google_sso() -> GoogleSSO:
    return GoogleSSO(
        client_id=settings.GOOGLE_CLIENT_ID or "",
        client_secret=settings.GOOGLE_CLIENT_SECRET or "",
        redirect_uri=f"{settings.FRONTEND_URL.rstrip('/')}/v1/google/callback",
        allow_insecure_http=bool(settings.OAUTHLIB_INSECURE_TRANSPORT)
        and not settings.is_production,
    )


@router.get("/login")
async def google_login(request: Request) -> dict[str, str]:
    sso = _get_google_sso()
    async with sso:
        response = await sso.get_login_redirect(
            redirect_uri=f"{settings.FRONTEND_URL.rstrip('/')}/v1/google/callback",
            params={"prompt": "consent", "access_type": "offline"},
        )
        location = response.headers.get("location", "")
        return {"authorization_url": location}


@router.post("/callback", response_model=TokenResponse)
async def google_callback(
    body: GoogleCallbackBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    sso = _get_google_sso()
    try:
        async with sso:
            sso_user = await sso.process_login(body.code, request)
    except (httpx.HTTPError, OAuthError) as exc:
        raise HTTPException(
            status_code=401,
            detail="Google login failed. The code may have expired or been reused.",
        ) from exc
    if sso_user is None:
        raise HTTPException(status_code=401, detail="Google login failed.")
    return await auth_controller.complete_google_login(db, sso_user)
