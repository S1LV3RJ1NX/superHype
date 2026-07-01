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
from urllib.parse import urlparse

import httpx

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


# LinkedIn's own URL shortener. A shortened post link hides the URN, so we
# follow the redirect to recover the canonical /posts/... URL, which carries the
# reshareable share/ugcPost id.
_SHORTLINK_HOSTS = {"lnkd.in"}
# Every redirect hop must land on one of these public LinkedIn hosts. lnkd.in is
# a general-purpose shortener whose target we do not control, so we must not let
# it (or any hop) redirect us to an arbitrary or internal address. Validating
# every hop against this fixed allowlist is what keeps the expansion free of SSRF.
_MAX_REDIRECTS = 5


def _host_allowed(hostname: str | None) -> bool:
    if not hostname:
        return False
    host = hostname.lower()
    return (
        host in _SHORTLINK_HOSTS
        or host == "linkedin.com"
        or host.endswith(".linkedin.com")
    )


async def resolve_post_urn(
    url: str | None,
    *,
    timeout: float = 5.0,
    transport: httpx.AsyncBaseTransport | None = None,
) -> str | None:
    """Like parse_post_urn, but first expands a lnkd.in short link.

    Reshares require a share or ugcPost URN. The /posts/... URL and the lnkd.in
    short link both lead to one; only the /feed/update/ URL is stuck as an
    activity URN (which reshare rejects). We parse directly when we can, and only
    hit the network to expand a short link, falling back to None on any error so
    a network blip never blocks campaign creation.

    Redirects are followed manually and every hop is checked against a fixed
    LinkedIn host allowlist (``_host_allowed``): a short link that tries to bounce
    us to an internal or arbitrary address is refused rather than fetched, so this
    cannot be turned into an SSRF. ``transport`` is injected in tests to stub the
    redirects.
    """
    if not url:
        return None
    direct = parse_post_urn(url)
    if direct is not None:
        return direct
    current = url.strip()
    if urlparse(current).hostname not in _SHORTLINK_HOSTS:
        return None
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(timeout),
            follow_redirects=False,
            transport=transport,
        ) as client:
            for _ in range(_MAX_REDIRECTS):
                if not _host_allowed(urlparse(current).hostname):
                    return None
                # HEAD would be lighter, but LinkedIn's shortener answers redirects
                # on GET; the body is never read, so nothing large is downloaded.
                resp = await client.request("GET", current)
                if resp.is_redirect and resp.next_request is not None:
                    current = str(resp.next_request.url)
                    continue
                # Not a redirect: validate the host we actually landed on, then
                # parse the final URL.
                if not _host_allowed(urlparse(str(resp.url)).hostname):
                    return None
                return parse_post_urn(str(resp.url))
    except httpx.HTTPError:
        return None
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
