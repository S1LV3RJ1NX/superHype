"""Tests for parsing a LinkedIn post URL into the URN used to act on the post."""

import httpx
import pytest

from app.core.linkedin_urn import parse_post_urn, resolve_post_urn

_ACTIVITY = "urn:li:activity:7123456789012345678"
_POSTS_SHARE = (
    "https://www.linkedin.com/posts/sarafpr_reinforcementlearning-"
    "bellmanequation-machinelearning-share-7477947017680543745-UWiY/"
    "?utm_source=share&utm_medium=member_desktop"
)


def test_feed_update_url():
    url = "https://www.linkedin.com/feed/update/urn:li:activity:7123456789012345678/"
    assert parse_post_urn(url) == _ACTIVITY


def test_posts_slug_url():
    url = (
        "https://www.linkedin.com/posts/jane-doe_some-slug-"
        "activity-7123456789012345678-AbCd"
    )
    assert parse_post_urn(url) == _ACTIVITY


def test_posts_share_slug_url_keeps_share_namespace():
    # The "Copy link to post" form, where the id is labeled "share". The id is a
    # share id, not an activity id, so we must keep the share namespace.
    url = (
        "https://www.linkedin.com/posts/sarafpr_upsc-upscprelims-upsc2026-"
        "share-7470530295751168000-cWvR/?utm_source=share&utm_medium=member_desktop"
    )
    assert parse_post_urn(url) == "urn:li:share:7470530295751168000"


def test_embed_share_url_keeps_share_namespace():
    url = (
        "https://www.linkedin.com/embed/feed/update/"
        "urn:li:share:7470530295751168000?collapsed=1"
    )
    assert parse_post_urn(url) == "urn:li:share:7470530295751168000"


def test_ugcpost_label_preserved():
    url = "https://www.linkedin.com/feed/update/urn:li:ugcPost:7123456789012345678/"
    assert parse_post_urn(url) == "urn:li:ugcPost:7123456789012345678"


def test_posts_url_without_label_falls_back_to_activity():
    url = (
        "https://www.linkedin.com/posts/jane-doe_a-slug-with-no-label-"
        "7123456789012345678-AbCd/"
    )
    assert parse_post_urn(url) == _ACTIVITY


def test_bare_urn_passthrough():
    assert parse_post_urn(_ACTIVITY) == _ACTIVITY


def test_short_numbers_in_slug_do_not_match():
    # Years and small counts in a slug must not be mistaken for an id.
    assert parse_post_urn("https://www.linkedin.com/posts/jane_2026-recap-fy24") is None


def test_junk_returns_none():
    assert parse_post_urn("https://example.com/not-a-post") is None
    assert parse_post_urn("") is None
    assert parse_post_urn(None) is None


@pytest.mark.asyncio
async def test_resolve_expands_short_link_to_share_urn():
    # A lnkd.in short link hides the URN; following the redirect recovers the
    # /posts/...-share-... URL, which carries the reshareable share URN.
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "lnkd.in":
            return httpx.Response(302, headers={"location": _POSTS_SHARE})
        return httpx.Response(200, text="ok")

    urn = await resolve_post_urn(
        "https://lnkd.in/p/dZ4eMaKV",
        transport=httpx.MockTransport(handler),
    )
    assert urn == "urn:li:share:7477947017680543745"


@pytest.mark.asyncio
async def test_resolve_parses_directly_without_network():
    # A URL that already carries a URN never hits the network: a transport that
    # would blow up proves we short-circuit on the direct parse.
    def boom(request: httpx.Request) -> httpx.Response:
        raise AssertionError("should not perform a network call")

    urn = await resolve_post_urn(_POSTS_SHARE, transport=httpx.MockTransport(boom))
    assert urn == "urn:li:share:7477947017680543745"


@pytest.mark.asyncio
async def test_resolve_ignores_non_shortlink_hosts():
    # Only lnkd.in is expanded; an unknown host with no URN returns None and does
    # not get fetched (no SSRF via arbitrary redirects).
    def boom(request: httpx.Request) -> httpx.Response:
        raise AssertionError("should not fetch a non-allowlisted host")

    urn = await resolve_post_urn(
        "https://example.com/some/post",
        transport=httpx.MockTransport(boom),
    )
    assert urn is None


@pytest.mark.asyncio
async def test_resolve_refuses_redirect_to_internal_host():
    # A crafted lnkd.in link that bounces to an internal address must be refused,
    # not followed: the internal host is never fetched (no SSRF).
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "lnkd.in":
            return httpx.Response(
                302, headers={"location": "http://169.254.169.254/latest/meta-data/"}
            )
        raise AssertionError("must not fetch a non-LinkedIn host")

    urn = await resolve_post_urn(
        "https://lnkd.in/p/evil",
        transport=httpx.MockTransport(handler),
    )
    assert urn is None


@pytest.mark.asyncio
async def test_resolve_network_error_falls_back_to_none():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    urn = await resolve_post_urn(
        "https://lnkd.in/p/dZ4eMaKV",
        transport=httpx.MockTransport(handler),
    )
    assert urn is None
