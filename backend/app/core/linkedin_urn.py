"""Parse a LinkedIn post URL into its activity URN.

LinkedIn post URLs embed the numeric activity id, e.g.
  https://www.linkedin.com/feed/update/urn:li:activity:7123456789012345678/
  https://www.linkedin.com/posts/jane-doe_some-slug-activity-7123456789012345678-AbCd
Both yield urn:li:activity:7123456789012345678. Used when a user pastes a URL
for an amplify target or a distribute seed.
"""

import re

_ACTIVITY_RE = re.compile(r"activity[:-](\d{6,})")


def parse_activity_urn(url: str | None) -> str | None:
    """Return urn:li:activity:{id} parsed from a LinkedIn URL, or None."""
    if not url:
        return None
    match = _ACTIVITY_RE.search(url)
    if match is None:
        return None
    return f"urn:li:activity:{match.group(1)}"
