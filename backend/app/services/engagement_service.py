"""Engagement ask: the assisted-manual prompt for a comment or like.

Until Community Management API access lands, comments and likes are a guided
human action rather than an API call. This factors the everything-a-person-
needs payload (a deep link to the target post and the suggested comment text)
into one place so the same ask renders in the web portal today and a Slack card
later without duplicating the logic.
"""

from dataclasses import dataclass

from app.config import settings
from app.core.linkedin_urn import build_post_permalink
from app.models.post import Post


def is_assisted(action: str) -> bool:
    """True when a comment or like is a guided human action, not an API call.

    Comments (including the author's own self-comment) and likes go through the
    socialActions API, which needs the w_member_social_feed scope (part of the
    Community Management API, not self-serve). Until that access lands they run
    assisted-manual: we resolve the target, deep-link the person to it, and they
    act in their own browser, so no LinkedIn token is needed and the reconnect
    gate does not apply. Posts and reshares are always automated through
    w_member_social. This is the single source of truth shared by the worker,
    the approve gate, and readiness checks.
    """
    return not settings.COMMUNITY_MANAGEMENT_ENABLED and action in (
        "comment",
        "like",
        "self_comment",
    )


@dataclass(frozen=True)
class EngagementAsk:
    """What a person needs to perform a comment or like by hand."""

    action: str
    target_url: str
    suggested_text: str | None


def engagement_ask(post: Post, target_urn: str) -> EngagementAsk:
    """Build the assisted-manual ask for a comment or like on a target post.

    A like carries no text; a comment (or the author's own self-comment) hands
    over the generated body to paste. For a self-comment the target is the
    author's own post, so the deep link points them back to it.
    """
    return EngagementAsk(
        action=post.action,
        target_url=build_post_permalink(target_urn) or "",
        suggested_text=(
            post.body if post.action in ("comment", "self_comment") else None
        ),
    )
