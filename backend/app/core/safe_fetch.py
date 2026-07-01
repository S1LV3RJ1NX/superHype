"""SSRF-guarded image fetching and the shared image upload policy.

External image URLs (campaign/post `image_url`) are user-controlled and get
fetched server-side at publish time. This module blocks requests to non-public
addresses (loopback, private ranges, link-local cloud metadata, etc.), restricts
the scheme, caps the download size, and validates the content type, so a member
cannot turn the worker into an SSRF proxy or exhaust its memory.
"""

import asyncio
import ipaddress
from urllib.parse import urlparse

import httpx

MAX_IMAGE_BYTES = 8 * 1024 * 1024  # 8 MB
# Raster formats only; SVG is excluded because it can carry active content.
ALLOWED_IMAGE_TYPES = {
    "image/png",
    "image/jpeg",
    "image/gif",
    "image/webp",
}
# Short-clip video for campaign media. Kept narrow to what LinkedIn accepts and
# what we can safely store; no streaming or exotic containers.
ALLOWED_VIDEO_TYPES = {
    "video/mp4",
    "video/quicktime",
}


class UnsafeURLError(Exception):
    """Raised when a URL is not safe to fetch (bad scheme or non-public host)."""


def is_allowed_image_type(content_type: str | None) -> bool:
    if not content_type:
        return False
    return content_type.split(";")[0].strip().lower() in ALLOWED_IMAGE_TYPES


def media_kind(content_type: str | None) -> str | None:
    """Return "image", "video", or None for a content type we accept as media."""
    if not content_type:
        return None
    normalized = content_type.split(";")[0].strip().lower()
    if normalized in ALLOWED_IMAGE_TYPES:
        return "image"
    if normalized in ALLOWED_VIDEO_TYPES:
        return "video"
    return None


async def _assert_public_host(host: str) -> None:
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(host, None)
    except OSError as exc:
        raise UnsafeURLError(f"Cannot resolve host: {host}") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            raise UnsafeURLError("URL resolves to a non-public address.")


async def fetch_image(
    url: str,
    *,
    max_bytes: int = MAX_IMAGE_BYTES,
    timeout: float = 30.0,
) -> tuple[bytes, str]:
    """Fetch an image from a public http(s) URL, size-capped and type-checked.

    Returns (data, content_type). Raises UnsafeURLError on any policy violation.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise UnsafeURLError("Only http(s) URLs are allowed.")
    if not parsed.hostname:
        raise UnsafeURLError("URL has no host.")
    await _assert_public_host(parsed.hostname)

    async with (
        httpx.AsyncClient(timeout=httpx.Timeout(timeout)) as client,
        client.stream("GET", url) as resp,
    ):
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "")
        if not is_allowed_image_type(content_type):
            raise UnsafeURLError("URL did not return an allowed image type.")
        data = b""
        async for chunk in resp.aiter_bytes():
            data += chunk
            if len(data) > max_bytes:
                raise UnsafeURLError("Image exceeds the size limit.")
    return data, content_type.split(";")[0].strip().lower()
