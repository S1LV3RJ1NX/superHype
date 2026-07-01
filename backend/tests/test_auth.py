"""Tests for the auth controller: domain rejection, bootstrap admin, upsert."""

import uuid

import pytest
from fastapi import HTTPException
from fastapi_sso.sso.base import OpenID
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.controllers.auth_controller import complete_google_login
from app.core.security import decode_access_token
from app.repositories.user_repo import user_repo


def _make_openid(
    email: str = "user@example.com",
    display_name: str = "Test User",
    google_sub: str | None = None,
    picture: str | None = None,
) -> OpenID:
    return OpenID(
        id=google_sub or str(uuid.uuid4()),
        email=email,
        display_name=display_name,
        picture=picture,
        provider="google",
    )


async def test_rejects_non_company_domain(db: AsyncSession, monkeypatch):
    monkeypatch.setattr(settings, "COMPANY_EMAIL_DOMAIN", "example.com")
    sso_user = _make_openid(email="outsider@gmail.com")
    with pytest.raises(HTTPException) as exc_info:
        await complete_google_login(db, sso_user)
    assert exc_info.value.status_code == 403


async def test_bootstrap_email_becomes_admin(db: AsyncSession, monkeypatch):
    monkeypatch.setattr(settings, "COMPANY_EMAIL_DOMAIN", "example.com")
    monkeypatch.setattr(settings, "BOOTSTRAP_ADMIN_EMAILS", "admin@example.com")
    sso_user = _make_openid(email="admin@example.com")
    result = await complete_google_login(db, sso_user)
    payload = decode_access_token(result.access_token)
    assert payload.role == "admin"


async def test_normal_email_becomes_viewer(db: AsyncSession, monkeypatch):
    monkeypatch.setattr(settings, "COMPANY_EMAIL_DOMAIN", "example.com")
    monkeypatch.setattr(settings, "BOOTSTRAP_ADMIN_EMAILS", "other@example.com")
    sso_user = _make_openid(email="regular@example.com")
    result = await complete_google_login(db, sso_user)
    payload = decode_access_token(result.access_token)
    assert payload.role == "viewer"


async def test_existing_user_is_reused(db: AsyncSession, monkeypatch):
    monkeypatch.setattr(settings, "COMPANY_EMAIL_DOMAIN", "example.com")
    monkeypatch.setattr(settings, "BOOTSTRAP_ADMIN_EMAILS", "")
    sso_user = _make_openid(email="repeat@example.com")

    await complete_google_login(db, sso_user)
    await complete_google_login(db, sso_user)

    user = await user_repo.get_by_email(db, "repeat@example.com")
    assert user is not None
    all_users = await user_repo.list(db, email="repeat@example.com")
    assert len(all_users) == 1


async def test_inactive_user_rejected(db: AsyncSession, monkeypatch):
    monkeypatch.setattr(settings, "COMPANY_EMAIL_DOMAIN", "example.com")
    monkeypatch.setattr(settings, "BOOTSTRAP_ADMIN_EMAILS", "")
    sso_user = _make_openid(email="disabled@example.com")
    await complete_google_login(db, sso_user)

    user = await user_repo.get_by_email(db, "disabled@example.com")
    assert user is not None
    user.is_active = False
    await db.commit()

    with pytest.raises(HTTPException) as exc_info:
        await complete_google_login(db, sso_user)
    assert exc_info.value.status_code == 403
    assert "disabled" in exc_info.value.detail.lower()
