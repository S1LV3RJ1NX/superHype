"""Engagement ask: the assisted-manual prompt for a comment or like.

Until Community Management API access lands, comments and likes are a guided
human action rather than an API call. This factors the everything-a-person-
needs payload (a deep link to the target post and the suggested comment text)
into one place so the same ask renders in the web portal today and a Slack card
later without duplicating the logic.
"""

from dataclasses import dataclass

from app.core.linkedin_urn import build_post_permalink
from app.core.x_urls import build_tweet_permalink
from app.models.post import Post


@dataclass(frozen=True)
class EngagementAsk:
    """What a person needs to perform a comment or like by hand."""

    action: str
    target_url: str
    suggested_text: str | None


def engagement_ask(post: Post, target_urn: str) -> EngagementAsk:
    """Build the assisted-manual ask for a comment, like, or quote on a target.

    A like carries no text; a comment, the author's own self-comment, and an X
    quote post all hand over the generated body to paste. For a self-comment the
    target is the author's own post, so the deep link points them back to it. The
    deep link resolves per platform: a LinkedIn feed permalink, or a tweet URL on
    X where replies and quotes are assisted-manual.
    """
    if post.platform == "x":
        target_url = build_tweet_permalink(target_urn) or ""
    else:
        target_url = build_post_permalink(target_urn) or ""
    return EngagementAsk(
        action=post.action,
        target_url=target_url,
        suggested_text=(
            post.body
            if post.action in ("comment", "self_comment", "repost_comment")
            else None
        ),
    )
