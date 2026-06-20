"""Tests for parsing a LinkedIn post URL into the URN used to act on the post."""

from app.core.linkedin_urn import parse_post_urn

_ACTIVITY = "urn:li:activity:7123456789012345678"


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
