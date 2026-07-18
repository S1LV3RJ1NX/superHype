"""Whether an engagement action is a guided human step or an automated API call.

A tiny, dependency-light predicate (settings plus the action string) so both the
schema boundary and the services/workers can share it without a schema having to
reach up into the services layer. The engagement ask payload itself lives in
services/engagement_service.py.
"""

from app.config import settings


def is_assisted(action: str, platform: str = "linkedin") -> bool:
    """True when a comment or like is a guided human action, not an API call.

    LinkedIn only: comments (including the author's own self-comment) and likes
    go through the socialActions API, which needs the w_member_social_feed scope
    (part of the Community Management API, not self-serve). Until that access
    lands they run assisted-manual: we resolve the target, deep-link the person
    to it, and they act in their own browser, so no LinkedIn token is needed and
    the reconnect gate does not apply. Posts and reshares are always automated
    through w_member_social.

    On X, replies to and quotes of a post the member did not author are blocked
    by the API (the Feb 2026 anti-spam rule, no self-serve workaround), so those
    two actions run assisted-manual: we deep-link the person to the target and
    they reply or quote in their own browser. Everything else on X (a tweet, the
    author's own self-comment reply on their own post, likes, bookmarks) is
    covered by the standard OAuth scopes and stays automated. This is the single
    source of truth shared by the worker, the approve gate, and readiness checks.
    """
    if platform == "x":
        return action in ("comment", "repost_comment")
    return not settings.COMMUNITY_MANAGEMENT_ENABLED and action in (
        "comment",
        "like",
        "self_comment",
    )
