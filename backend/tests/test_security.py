"""Tests for core/security.py: JWT creation and decoding."""

import uuid
from datetime import timedelta

import pytest
from fastapi import HTTPException

from app.core.security import create_access_token, decode_access_token


async def test_create_decode_roundtrip():
    uid = uuid.uuid4()
    token = await create_access_token(user_id=uid, email="a@b.com", role="viewer")
    payload = decode_access_token(token)
    assert payload.user_id == uid
    assert payload.email == "a@b.com"
    assert payload.role == "viewer"


async def test_expired_token_raises_401():
    uid = uuid.uuid4()
    token = await create_access_token(
        user_id=uid,
        email="a@b.com",
        role="viewer",
        expires_delta=timedelta(seconds=-1),
    )
    with pytest.raises(HTTPException) as exc_info:
        decode_access_token(token)
    assert exc_info.value.status_code == 401
    assert "expired" in exc_info.value.detail.lower()


async def test_tampered_token_raises_401():
    uid = uuid.uuid4()
    token = await create_access_token(user_id=uid, email="a@b.com", role="viewer")
    tampered = token[:-4] + "XXXX"
    with pytest.raises(HTTPException) as exc_info:
        decode_access_token(tampered)
    assert exc_info.value.status_code == 401


async def test_garbage_token_raises_401():
    with pytest.raises(HTTPException) as exc_info:
        decode_access_token("not.a.jwt")
    assert exc_info.value.status_code == 401
