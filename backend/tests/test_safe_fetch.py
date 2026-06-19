"""Tests for the SSRF-guarded image fetcher."""

import httpx
import pytest

from app.core import safe_fetch
from app.core.safe_fetch import UnsafeURLError, fetch_image, is_allowed_image_type


def test_is_allowed_image_type():
    assert is_allowed_image_type("image/png")
    assert is_allowed_image_type("image/jpeg; charset=binary")
    assert not is_allowed_image_type("image/svg+xml")
    assert not is_allowed_image_type("text/html")
    assert not is_allowed_image_type(None)


@pytest.mark.asyncio
async def test_rejects_non_http_scheme():
    with pytest.raises(UnsafeURLError):
        await fetch_image("file:///etc/passwd")


@pytest.mark.asyncio
async def test_rejects_private_host(monkeypatch):
    import asyncio

    # 169.254.169.254 is the cloud metadata endpoint: must be blocked.
    async def _fake_getaddrinfo(host, port):
        return [(2, 1, 6, "", ("169.254.169.254", 0))]

    loop = asyncio.get_running_loop()
    monkeypatch.setattr(loop, "getaddrinfo", _fake_getaddrinfo)
    with pytest.raises(UnsafeURLError):
        await fetch_image("http://metadata.internal/latest")


@pytest.mark.asyncio
async def test_size_cap_enforced(monkeypatch):
    async def _ok_host(host):
        return None

    monkeypatch.setattr(safe_fetch, "_assert_public_host", _ok_host)

    big = b"x" * 100

    def _handler(request):
        return httpx.Response(200, headers={"content-type": "image/png"}, content=big)

    transport = httpx.MockTransport(_handler)

    orig_client = httpx.AsyncClient

    def _client(*a, **k):
        k["transport"] = transport
        return orig_client(*a, **k)

    monkeypatch.setattr(httpx, "AsyncClient", _client)

    with pytest.raises(UnsafeURLError):
        await fetch_image("http://example.com/x.png", max_bytes=10)


@pytest.mark.asyncio
async def test_rejects_non_image_content_type(monkeypatch):
    async def _ok_host(host):
        return None

    monkeypatch.setattr(safe_fetch, "_assert_public_host", _ok_host)

    def _handler(request):
        return httpx.Response(
            200, headers={"content-type": "text/html"}, content=b"<html>"
        )

    transport = httpx.MockTransport(_handler)
    orig_client = httpx.AsyncClient

    def _client(*a, **k):
        k["transport"] = transport
        return orig_client(*a, **k)

    monkeypatch.setattr(httpx, "AsyncClient", _client)

    with pytest.raises(UnsafeURLError):
        await fetch_image("http://example.com/x")


@pytest.mark.asyncio
async def test_fetch_image_happy(monkeypatch):
    async def _ok_host(host):
        return None

    monkeypatch.setattr(safe_fetch, "_assert_public_host", _ok_host)

    payload = b"\x89PNG\r\n"

    def _handler(request):
        return httpx.Response(
            200, headers={"content-type": "image/png"}, content=payload
        )

    transport = httpx.MockTransport(_handler)
    orig_client = httpx.AsyncClient

    def _client(*a, **k):
        k["transport"] = transport
        return orig_client(*a, **k)

    monkeypatch.setattr(httpx, "AsyncClient", _client)

    data, ctype = await fetch_image("http://example.com/logo.png")
    assert data == payload
    assert ctype == "image/png"
