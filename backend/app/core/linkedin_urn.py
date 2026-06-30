"""Parse a LinkedIn post URL into the URN used to act on that post.

Most people amplify a post the obvious way: hit "Copy link to post" (or "Embed
this post") on LinkedIn and paste it in. Those links come in several shapes and
embed the post id under different entity labels:
  https://www.linkedin.com/feed/update/urn:li:activity:7123456789012345678/
  https://www.linkedin.com/posts/jane-doe_slug-activity-7123456789012345678-AbCd
  https://www.linkedin.com/posts/jane_slug-share-7470530295751168000-cWvR
  https://www.linkedin.com/embed/feed/update/urn:li:share:7470530295751168000
  urn:li:activity:7123456789012345678

The label matters: a post's activity id and its share id are different numbers,
so we must keep the namespace LinkedIn gave us (activity, share, or ugcPost)
rather than coercing everything to activity. The likes, comments, and reshare
APIs all accept any of these URN types as the target.
"""

import re

# An id tagged with a known entity label, in either the urn (colon) or the
# /posts/ slug (hyphen) form. The label is preserved in the returned URN.
_LABELED_RE = re.compile(r"(activity|share|ugcPost)[:-](\d{6,})", re.IGNORECASE)
# Fallback for a link that carries no label: a LinkedIn id is a long (17+ digit)
# run, far longer than anything a human-readable slug holds, so this catches the
# bare id without grabbing a year or count. Unlabeled ids default to activity,
# the historical feed-update form.
_BARE_ID_RE = re.compile(r"\d{17,}")

_CANONICAL_LABEL = {"activity": "activity", "share": "share", "ugcpost": "ugcPost"}


def parse_post_urn(url: str | None) -> str | None:
    """Return the urn:li:{activity|share|ugcPost}:{id} for a LinkedIn URL, or None."""
    if not url:
        return None
    match = _LABELED_RE.search(url)
    if match is not None:
        label = _CANONICAL_LABEL[match.group(1).lower()]
        return f"urn:li:{label}:{match.group(2)}"
    bare = _BARE_ID_RE.search(url)
    if bare is not None:
        return f"urn:li:activity:{bare.group(0)}"
    return None


def build_post_permalink(urn: str | None) -> str | None:
    """Public feed URL for a post URN, for deep-linking a person to act on it.

    LinkedIn renders any post URN (activity, share, or ugcPost) at
    /feed/update/{urn}/, so this is the link we hand a member when a comment or
    like is an assisted-manual action: they open the post and act by hand.
    """
    if not urn:
        return None
    return f"https://www.linkedin.com/feed/update/{urn}/"
