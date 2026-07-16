"""Parse an X (Twitter) post URL into the tweet id used to act on it.

People amplify a tweet by pasting its share link. All the common shapes carry
the numeric tweet id in a /status/ segment:
  https://x.com/someone/status/1790000000000000000
  https://twitter.com/someone/status/1790000000000000000?s=20
  https://mobile.twitter.com/i/web/status/1790000000000000000
  1790000000000000000 (a bare id)

Unlike LinkedIn there is only one id namespace, so the parsed value is the
plain numeric id string; it is what every v2 endpoint (like, bookmark, reply,
quote) accepts as the target.
"""

import re
from urllib.parse import urlparse

_STATUS_RE = re.compile(r"/status(?:es)?/(\d{5,})")
_BARE_ID_RE = re.compile(r"^\d{5,}$")

_X_HOSTS = {"x.com", "twitter.com", "www.x.com", "www.twitter.com"}


def _host_is_x(hostname: str | None) -> bool:
    if not hostname:
        return False
    host = hostname.lower()
    return host in _X_HOSTS or host.endswith(".twitter.com") or host.endswith(".x.com")


def parse_tweet_id(url: str | None) -> str | None:
    """Return the numeric tweet id for an X post URL (or a bare id), or None."""
    if not url:
        return None
    candidate = url.strip()
    if _BARE_ID_RE.match(candidate):
        return candidate
    parsed = urlparse(candidate)
    if not _host_is_x(parsed.hostname):
        return None
    match = _STATUS_RE.search(parsed.path)
    return match.group(1) if match else None


def build_tweet_permalink(tweet_id: str | None) -> str | None:
    """Public URL for a tweet id, for deep-linking a person to it."""
    if not tweet_id:
        return None
    return f"https://x.com/i/web/status/{tweet_id}"
