"""Assisted-manual predicate and ask payload, including the X reply/quote path."""

from app.core.engagement import is_assisted
from app.models.post import Post
from app.services.engagement_service import engagement_ask


def test_x_reply_and_quote_are_assisted():
    # X blocks programmatic replies/quotes of others' posts, so both run
    # assisted-manual regardless of the LinkedIn community-management flag.
    assert is_assisted("comment", "x") is True
    assert is_assisted("repost_comment", "x") is True


def test_x_automated_actions_are_not_assisted():
    for action in ("post", "self_comment", "like", "bookmark"):
        assert is_assisted(action, "x") is False, action


def test_linkedin_repost_stays_automated():
    # A LinkedIn reshare goes through w_member_social; only comment/like/self are
    # assisted while community management is off.
    assert is_assisted("repost_comment", "linkedin") is False


def test_engagement_ask_x_uses_tweet_permalink():
    post = Post(platform="x", action="comment", body="great thread")
    ask = engagement_ask(post, "1790000000000000000")
    assert ask.target_url == "https://x.com/i/web/status/1790000000000000000"
    assert ask.suggested_text == "great thread"


def test_engagement_ask_x_quote_hands_over_commentary():
    post = Post(platform="x", action="repost_comment", body="worth a read")
    ask = engagement_ask(post, "1790000000000000000")
    assert ask.target_url == "https://x.com/i/web/status/1790000000000000000"
    assert ask.suggested_text == "worth a read"


def test_engagement_ask_linkedin_uses_feed_permalink():
    post = Post(platform="linkedin", action="comment", body="nice")
    ask = engagement_ask(post, "urn:li:share:123")
    assert "linkedin.com" in ask.target_url
    assert ask.suggested_text == "nice"
