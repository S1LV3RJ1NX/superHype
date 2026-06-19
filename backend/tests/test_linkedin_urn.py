"""Tests for parsing a LinkedIn post URL into an activity URN."""

from app.core.linkedin_urn import parse_activity_urn

_URN = "urn:li:activity:7123456789012345678"


def test_feed_update_url():
    url = "https://www.linkedin.com/feed/update/urn:li:activity:7123456789012345678/"
    assert parse_activity_urn(url) == _URN


def test_posts_slug_url():
    url = (
        "https://www.linkedin.com/posts/jane-doe_some-slug-"
        "activity-7123456789012345678-AbCd"
    )
    assert parse_activity_urn(url) == _URN


def test_bare_urn_passthrough():
    assert parse_activity_urn(_URN) == _URN


def test_junk_returns_none():
    assert parse_activity_urn("https://example.com/not-a-post") is None
    assert parse_activity_urn("") is None
    assert parse_activity_urn(None) is None
