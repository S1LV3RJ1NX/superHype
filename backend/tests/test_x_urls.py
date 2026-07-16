"""Tests for X post URL parsing and permalink building (pure functions)."""

import pytest

from app.core.x_urls import build_tweet_permalink, parse_tweet_id


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://x.com/someone/status/1790000000000000000", "1790000000000000000"),
        (
            "https://twitter.com/someone/status/1790000000000000000?s=20&t=abc",
            "1790000000000000000",
        ),
        (
            "https://mobile.twitter.com/i/web/status/1790000000000000000",
            "1790000000000000000",
        ),
        ("https://www.x.com/a_b/statuses/12345678901", "12345678901"),
        ("1790000000000000000", "1790000000000000000"),
        ("  https://x.com/someone/status/123456789  ", "123456789"),
    ],
)
def test_parse_tweet_id_accepts_common_shapes(url, expected):
    assert parse_tweet_id(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        None,
        "",
        "not a url",
        # LinkedIn links must not resolve as tweets.
        "https://www.linkedin.com/feed/update/urn:li:activity:7123456789012345678/",
        # Right path shape on the wrong host (lookalike domain).
        "https://evil.com/someone/status/1790000000000000000",
        "https://x.com.evil.com/someone/status/1790000000000000000",
        # An X profile link with no status segment.
        "https://x.com/someone",
        # Too-short numeric run is not a tweet id.
        "1234",
    ],
)
def test_parse_tweet_id_rejects_non_tweets(url):
    assert parse_tweet_id(url) is None


def test_build_tweet_permalink_round_trip():
    url = build_tweet_permalink("1790000000000000000")
    assert url == "https://x.com/i/web/status/1790000000000000000"
    assert parse_tweet_id(url) == "1790000000000000000"


def test_build_tweet_permalink_none():
    assert build_tweet_permalink(None) is None
    assert build_tweet_permalink("") is None
