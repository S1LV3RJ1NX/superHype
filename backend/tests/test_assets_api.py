"""API tests for asset upload validation and serve round-trip."""

import pytest

pytestmark = pytest.mark.asyncio

_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


async def test_upload_and_serve_round_trip(client, as_role):
    async with as_role("editor"):
        up = await client.post(
            "/v1/assets",
            files={"file": ("logo.png", _PNG, "image/png")},
        )
        assert up.status_code == 201
        asset_id = up.json()["id"]

        served = await client.get(f"/v1/assets/{asset_id}")
    assert served.status_code == 200
    assert served.headers["content-type"].startswith("image/png")
    assert served.content == _PNG


async def test_upload_writes_audit(client, as_role, db):
    from sqlalchemy import select

    from app.models.audit_log import AuditLog

    async with as_role("editor"):
        up = await client.post(
            "/v1/assets",
            files={"file": ("logo.png", _PNG, "image/png")},
        )
        assert up.status_code == 201
    rows = (
        (await db.execute(select(AuditLog).where(AuditLog.action == "asset_uploaded")))
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].detail["content_type"] == "image/png"


async def test_rejects_svg(client, as_role):
    async with as_role("editor"):
        resp = await client.post(
            "/v1/assets",
            files={"file": ("x.svg", b"<svg></svg>", "image/svg+xml")},
        )
    assert resp.status_code == 415


async def test_viewer_cannot_upload(client, as_role):
    async with as_role("viewer"):
        resp = await client.post(
            "/v1/assets",
            files={"file": ("logo.png", _PNG, "image/png")},
        )
    assert resp.status_code == 403


async def test_rejects_non_image(client, as_role):
    async with as_role("editor"):
        resp = await client.post(
            "/v1/assets",
            files={"file": ("notes.txt", b"hello", "text/plain")},
        )
    assert resp.status_code == 415


async def test_rejects_oversize(client, as_role):
    big = b"\x00" * (8 * 1024 * 1024 + 1)
    async with as_role("editor"):
        resp = await client.post(
            "/v1/assets",
            files={"file": ("big.png", big, "image/png")},
        )
    assert resp.status_code == 413


_MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64


async def test_accepts_video_round_trip(client, as_role):
    async with as_role("editor"):
        up = await client.post(
            "/v1/assets",
            files={"file": ("clip.mp4", _MP4, "video/mp4")},
        )
        assert up.status_code == 201
        asset_id = up.json()["id"]
        served = await client.get(f"/v1/assets/{asset_id}")
    assert served.status_code == 200
    assert served.headers["content-type"].startswith("video/mp4")
    assert served.content == _MP4


async def test_rejects_oversize_video(client, as_role, monkeypatch):
    from app.controllers import asset_controller

    monkeypatch.setattr(asset_controller.settings, "MAX_VIDEO_BYTES", 128)
    async with as_role("editor"):
        resp = await client.post(
            "/v1/assets",
            files={"file": ("big.mp4", b"\x00" * 200, "video/mp4")},
        )
    assert resp.status_code == 413
