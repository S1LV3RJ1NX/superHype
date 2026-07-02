"""Tests for the Slack integration: signature, client, service, and endpoint.

Every outbound Slack call is stubbed (a fake client for service logic, an httpx
MockTransport for the raw client), so nothing here touches the network.
"""

import hashlib
import hmac
import json
import uuid
from datetime import UTC, datetime
from urllib.parse import urlencode

import httpx
import pytest

from app.config import settings
from app.integrations.slack import SlackClient, SlackError, verify_signature
from app.models.campaign import Campaign
from app.models.post import Post
from app.models.slack_identity import SlackIdentity
from app.models.user import User
from app.services import slack_service

# asyncio_mode = "auto" runs the async tests without a per-test marker, so the
# synchronous signature tests are not forced onto the event loop.


# --- fakes -----------------------------------------------------------------


class FakeSlackClient:
    """Records outbound calls; resolves emails from an injected map."""

    def __init__(self, email_to_id: dict[str, str] | None = None) -> None:
        self._email_to_id = email_to_id or {}
        self.lookups = 0
        self.messages: list[tuple] = []
        self.responses: list[tuple] = []
        self.closed = False

    async def lookup_user_by_email(self, email: str) -> str | None:
        self.lookups += 1
        return self._email_to_id.get(email)

    async def open_dm(self, slack_user_id: str) -> str:
        return f"D-{slack_user_id}"

    async def post_message(self, channel, *, text, blocks=None) -> str:
        self.messages.append((channel, text, blocks))
        return "ts.1"

    async def respond(self, response_url, payload) -> None:
        self.responses.append((response_url, payload))

    async def aclose(self) -> None:
        self.closed = True


# --- db helpers ------------------------------------------------------------


async def _user(db, email: str | None = None) -> User:
    u = User(email=email or f"{uuid.uuid4().hex}@corp.com", role="editor")
    db.add(u)
    await db.flush()
    return u


async def _launched_campaign(db) -> Campaign:
    c = Campaign(
        title="Launch week",
        type="amplify",
        status="publishing",
        seed_urn="urn:li:activity:1",
        launched_at=datetime.now(UTC),
    )
    db.add(c)
    await db.flush()
    return c


async def _post(
    db,
    campaign,
    user,
    action="like",
    status="scheduled",
    *,
    engagement_url=None,
    body=None,
) -> Post:
    p = Post(
        campaign_id=campaign.id,
        user_id=user.id,
        action=action,
        status=status,
        idempotency_key=uuid.uuid4().hex,
        engagement_url=engagement_url,
        body=body,
    )
    db.add(p)
    await db.flush()
    return p


# --- signature -------------------------------------------------------------


def _sign(secret: str, timestamp: str, body: bytes) -> str:
    base = b"v0:" + timestamp.encode() + b":" + body
    return "v0=" + hmac.new(secret.encode(), base, hashlib.sha256).hexdigest()


def test_verify_signature_accepts_valid():
    body = b"payload=%7B%7D"
    ts = str(int(datetime.now(UTC).timestamp()))
    sig = _sign("shh", ts, body)
    assert verify_signature(
        signing_secret="shh", timestamp=ts, body=body, signature=sig
    )


def test_verify_signature_rejects_tampered_body():
    ts = str(int(datetime.now(UTC).timestamp()))
    sig = _sign("shh", ts, b"payload=a")
    assert not verify_signature(
        signing_secret="shh", timestamp=ts, body=b"payload=b", signature=sig
    )


def test_verify_signature_rejects_stale_timestamp():
    body = b"x"
    ts = str(int(datetime.now(UTC).timestamp()) - 10_000)
    sig = _sign("shh", ts, body)
    assert not verify_signature(
        signing_secret="shh", timestamp=ts, body=body, signature=sig
    )


def test_verify_signature_rejects_missing_parts():
    assert not verify_signature(
        signing_secret=None, timestamp="1", body=b"x", signature="v0=abc"
    )
    assert not verify_signature(
        signing_secret="shh", timestamp=None, body=b"x", signature="v0=abc"
    )


# --- raw client ------------------------------------------------------------


async def test_slack_client_happy_path():
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("users.lookupByEmail"):
            return httpx.Response(200, json={"ok": True, "user": {"id": "U9"}})
        if path.endswith("conversations.open"):
            return httpx.Response(200, json={"ok": True, "channel": {"id": "D9"}})
        if path.endswith("chat.postMessage"):
            return httpx.Response(200, json={"ok": True, "ts": "123.45"})
        return httpx.Response(200, json={"ok": True})

    client = SlackClient("xoxb-test", transport=httpx.MockTransport(handler))
    try:
        assert await client.lookup_user_by_email("a@corp.com") == "U9"
        assert await client.open_dm("U9") == "D9"
        assert await client.post_message("D9", text="hi") == "123.45"
    finally:
        await client.aclose()


async def test_slack_client_lookup_miss_returns_none():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": False, "error": "users_not_found"})

    client = SlackClient("xoxb-test", transport=httpx.MockTransport(handler))
    try:
        assert await client.lookup_user_by_email("nobody@corp.com") is None
    finally:
        await client.aclose()


async def test_slack_client_raises_on_api_error():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": False, "error": "channel_not_found"})

    client = SlackClient("xoxb-test", transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(SlackError):
            await client.open_dm("U-bad")
    finally:
        await client.aclose()


# --- service: identity + notify --------------------------------------------


async def test_resolve_identity_caches_after_first_lookup(db):
    user = await _user(db, email="jane@corp.com")
    client = FakeSlackClient({"jane@corp.com": "U-JANE"})

    ident1 = await slack_service.resolve_identity(db, client, user)
    assert ident1 is not None
    assert ident1.slack_user_id == "U-JANE"
    assert client.lookups == 1

    # Second call hits the cached row, not Slack.
    ident2 = await slack_service.resolve_identity(db, client, user)
    assert ident2 is not None
    assert client.lookups == 1


async def test_resolve_identity_none_when_no_slack_match(db):
    user = await _user(db, email="ghost@corp.com")
    client = FakeSlackClient({})
    assert await slack_service.resolve_identity(db, client, user) is None


async def test_notify_participant_posts_bundled_card(db):
    user = await _user(db, email="ann@corp.com")
    campaign = await _launched_campaign(db)
    posts = [
        await _post(db, campaign, user, action="post"),
        await _post(db, campaign, user, action="like"),
        await _post(db, campaign, user, action="comment"),
    ]
    await db.commit()

    client = FakeSlackClient({"ann@corp.com": "U-ANN"})
    await slack_service.notify_participant(db, client, campaign, user, posts)

    assert len(client.messages) == 1
    channel, text, blocks = client.messages[0]
    assert channel == "D-U-ANN"
    assert "3" in text
    # The button block carries approve + skip + open-portal buttons.
    action_block = next(
        b
        for b in blocks
        if b["type"] == "actions"
        and any(el.get("action_id") == "campaign_approve_all" for el in b["elements"])
    )
    action_ids = {el.get("action_id") for el in action_block["elements"]}
    assert "campaign_approve_all" in action_ids
    assert "campaign_skip_all" in action_ids
    # A per-action opt-in checkbox block, all actions ticked by default.
    checkbox_block = next(
        b for b in blocks if b.get("block_id") == "campaign_action_select"
    )
    checkboxes = checkbox_block["elements"][0]
    assert checkboxes["type"] == "checkboxes"
    values = {opt["value"] for opt in checkboxes["options"]}
    assert values == {"post", "like", "comment"}
    # Every option starts ticked so approving with no changes lets everything go.
    assert checkboxes["options"] == checkboxes["initial_options"]


async def test_notify_participant_skips_without_identity(db):
    user = await _user(db, email="none@corp.com")
    campaign = await _launched_campaign(db)
    posts = [await _post(db, campaign, user)]
    await db.commit()

    client = FakeSlackClient({})  # no Slack match
    await slack_service.notify_participant(db, client, campaign, user, posts)
    assert client.messages == []


async def test_notify_engagements_posts_mark_done_card(db):
    user = await _user(db, email="eng@corp.com")
    campaign = await _launched_campaign(db)
    posts = [
        await _post(
            db,
            campaign,
            user,
            action="like",
            status="action_required",
            engagement_url="https://www.linkedin.com/feed/update/urn:li:activity:1",
        ),
        await _post(
            db,
            campaign,
            user,
            action="comment",
            status="action_required",
            engagement_url="https://www.linkedin.com/feed/update/urn:li:activity:1",
            body="Great post, love the RL angle.",
        ),
    ]
    await db.commit()

    client = FakeSlackClient({"eng@corp.com": "U-ENG"})
    await slack_service.notify_engagements(db, client, campaign, user, posts)

    # The card, plus one standalone plain message with the comment for mobile copy.
    assert len(client.messages) == 2
    channel, text, blocks = client.messages[0]
    assert channel == "D-U-ENG"
    # Like + comment on the same post collapse into one grouped ask.
    assert "1 LinkedIn engagement" in text
    # The standalone message is exactly the comment (no blocks), so mobile
    # long-press "Copy text" yields only the comment.
    copy_channel, copy_text, copy_blocks = client.messages[1]
    assert copy_channel == "D-U-ENG"
    assert copy_text == "Great post, love the RL angle."
    assert copy_blocks is None
    # The mark-done bundle carries ack + skip, never approve/publish controls.
    action_block = next(b for b in blocks if b["type"] == "actions")
    action_ids = {el.get("action_id") for el in action_block["elements"]}
    assert action_ids == {"engagement_ack_all", "engagement_skip_all"}
    # One combined section: labeled like-and-comment, pointing to the follow-up
    # message that carries the copyable comment. The comment text is not inlined
    # in the card anymore (no fenced code block), only in the standalone message.
    combined = next(
        b
        for b in blocks
        if b.get("type") == "section"
        and "Like and comment on this teammate's post" in b["text"]["text"]
    )
    combined_text = combined["text"]["text"]
    assert (
        "Copy the comment from the next message and paste it on the post"
        in combined_text
    )
    assert "Great post, love the RL angle." not in combined_text
    # No separate bare "Like" entry survived the grouping.
    like_only = [
        b
        for b in blocks
        if b.get("type") == "section"
        and b["text"]["text"].startswith("*Like this teammate's post*")
    ]
    assert like_only == []


async def test_notify_engagements_separate_targets_stay_separate(db):
    user = await _user(db, email="multi@corp.com")
    campaign = await _launched_campaign(db)
    posts = [
        await _post(
            db,
            campaign,
            user,
            action="comment",
            status="action_required",
            engagement_url="https://www.linkedin.com/feed/update/urn:li:activity:1",
            body="Comment for post one.",
        ),
        await _post(
            db,
            campaign,
            user,
            action="like",
            status="action_required",
            engagement_url="https://www.linkedin.com/feed/update/urn:li:activity:2",
        ),
    ]
    await db.commit()

    client = FakeSlackClient({"multi@corp.com": "U-MULTI"})
    await slack_service.notify_engagements(db, client, campaign, user, posts)

    _channel, text, blocks = client.messages[0]
    # Different posts -> two separate grouped asks, not one merged entry.
    assert "2 LinkedIn engagement" in text
    labels = [
        b["text"]["text"]
        for b in blocks
        if b.get("type") == "section" and b["text"]["text"].startswith("*")
    ]
    assert any("Comment on this teammate's post" in line for line in labels)
    assert any("Like this teammate's post" in line for line in labels)


async def test_notify_reconnect_dms_link(db):
    user = await _user(db, email="stale@corp.com")
    client = FakeSlackClient({"stale@corp.com": "U-STALE"})
    await slack_service.notify_reconnect(db, client, user)

    assert len(client.messages) == 1
    channel, text, _blocks = client.messages[0]
    assert channel == "D-U-STALE"
    assert "reconnect" in text.lower()
    assert "/app/connections" in text


# --- service: interactions -------------------------------------------------


def _block_actions(slack_user_id: str, action_id: str, campaign_id) -> dict:
    return {
        "type": "block_actions",
        "user": {"id": slack_user_id},
        "response_url": "https://hooks.slack.test/abc",
        "actions": [{"action_id": action_id, "value": str(campaign_id)}],
    }


def _approve_with_selection(slack_user_id, campaign_id, selected_actions) -> dict:
    """An Approve-all click carrying the ticked per-action checkbox state."""
    payload = _block_actions(slack_user_id, "campaign_approve_all", campaign_id)
    payload["state"] = {
        "values": {
            "campaign_action_select": {
                "campaign_action_toggle": {
                    "type": "checkboxes",
                    "selected_options": [{"value": a} for a in selected_actions],
                }
            }
        }
    }
    return payload


async def _identity(db, user, slack_user_id="U-CLICK"):
    ident = SlackIdentity(
        user_id=user.id, slack_user_id=slack_user_id, slack_dm_channel="D1"
    )
    db.add(ident)
    await db.flush()
    return ident


async def test_handle_interaction_approve_settles_and_enqueues(db, enqueued):
    user = await _user(db)
    campaign = await _launched_campaign(db)
    p1 = await _post(db, campaign, user, action="like")
    p2 = await _post(db, campaign, user, action="comment")
    await _identity(db, user)
    await db.commit()

    client = FakeSlackClient()
    payload = _block_actions("U-CLICK", "campaign_approve_all", campaign.id)
    await slack_service.handle_interaction(db, client, payload)

    await db.refresh(p1)
    await db.refresh(p2)
    assert p1.status == "approved"
    assert p2.status == "approved"
    published = [c for c in enqueued if c[0] == "publish_post"]
    assert len(published) == 2
    assert client.responses and "Approved" in client.responses[-1][1]["text"]


async def test_handle_interaction_approve_only_checked_actions(db, enqueued):
    # With the reshare unticked, Approve approves the like and comment and skips
    # the reshare in the same interaction.
    user = await _user(db)
    campaign = await _launched_campaign(db)
    like = await _post(db, campaign, user, action="like")
    comment = await _post(db, campaign, user, action="comment")
    repost = await _post(db, campaign, user, action="repost_comment")
    await _identity(db, user)
    await db.commit()

    client = FakeSlackClient()
    payload = _approve_with_selection("U-CLICK", campaign.id, {"like", "comment"})
    await slack_service.handle_interaction(db, client, payload)

    await db.refresh(like)
    await db.refresh(comment)
    await db.refresh(repost)
    assert like.status == "approved"
    assert comment.status == "approved"
    assert repost.status == "skipped"
    reply = client.responses[-1][1]["text"]
    assert "Approved 2" in reply and "skipped 1" in reply


async def test_handle_interaction_unticking_post_drops_self_comment(db):
    # A self-comment cannot run without the person's own post, so unticking the
    # post skips the self-comment even if it was left ticked.
    user = await _user(db)
    campaign = await _launched_campaign(db)
    post = await _post(db, campaign, user, action="post")
    self_comment = await _post(db, campaign, user, action="self_comment")
    await _identity(db, user)
    await db.commit()

    client = FakeSlackClient()
    payload = _approve_with_selection("U-CLICK", campaign.id, {"self_comment"})
    await slack_service.handle_interaction(db, client, payload)

    await db.refresh(post)
    await db.refresh(self_comment)
    assert post.status == "skipped"
    assert self_comment.status == "skipped"


async def test_handle_interaction_skip_settles(db):
    user = await _user(db)
    campaign = await _launched_campaign(db)
    p1 = await _post(db, campaign, user, action="like")
    await _identity(db, user)
    await db.commit()

    client = FakeSlackClient()
    payload = _block_actions("U-CLICK", "campaign_skip_all", campaign.id)
    await slack_service.handle_interaction(db, client, payload)

    await db.refresh(p1)
    assert p1.status == "skipped"
    assert "Skipped" in client.responses[-1][1]["text"]


async def test_handle_interaction_reconnect_blocks_approve(db, enqueued):
    user = await _user(db)
    campaign = await _launched_campaign(db)
    # A self-post is not assisted, so approve hits the reconnect gate; with no
    # connected account it must refuse and leave the post untouched.
    p1 = await _post(db, campaign, user, action="post")
    await _identity(db, user)
    await db.commit()

    client = FakeSlackClient()
    payload = _block_actions("U-CLICK", "campaign_approve_all", campaign.id)
    await slack_service.handle_interaction(db, client, payload)

    await db.refresh(p1)
    assert p1.status == "scheduled"
    assert not [c for c in enqueued if c[0] == "publish_post"]
    assert "Reconnect" in client.responses[-1][1]["text"]


async def test_handle_interaction_ack_marks_engagements_done(db):
    user = await _user(db)
    campaign = await _launched_campaign(db)
    p1 = await _post(db, campaign, user, action="like", status="action_required")
    p2 = await _post(db, campaign, user, action="comment", status="action_required")
    # A scheduled post is not part of the engagement bundle and must be left alone.
    p3 = await _post(db, campaign, user, action="post", status="scheduled")
    await _identity(db, user)
    await db.commit()

    client = FakeSlackClient()
    payload = _block_actions("U-CLICK", "engagement_ack_all", campaign.id)
    await slack_service.handle_interaction(db, client, payload)

    await db.refresh(p1)
    await db.refresh(p2)
    await db.refresh(p3)
    assert p1.status == "acknowledged"
    assert p2.status == "acknowledged"
    assert p3.status == "scheduled"
    assert "Marked" in client.responses[-1][1]["text"]


async def test_handle_interaction_engagement_skip(db):
    user = await _user(db)
    campaign = await _launched_campaign(db)
    p1 = await _post(db, campaign, user, action="comment", status="action_required")
    await _identity(db, user)
    await db.commit()

    client = FakeSlackClient()
    payload = _block_actions("U-CLICK", "engagement_skip_all", campaign.id)
    await slack_service.handle_interaction(db, client, payload)

    await db.refresh(p1)
    assert p1.status == "skipped"
    assert "Skipped" in client.responses[-1][1]["text"]


async def test_handle_interaction_unknown_slack_user(db):
    client = FakeSlackClient()
    payload = _block_actions("U-STRANGER", "campaign_approve_all", uuid.uuid4())
    await slack_service.handle_interaction(db, client, payload)
    assert "could not match" in client.responses[-1][1]["text"].lower()


async def test_handle_interaction_ignores_non_action_button(db):
    user = await _user(db)
    campaign = await _launched_campaign(db)
    await _identity(db, user)
    await db.commit()

    client = FakeSlackClient()
    payload = _block_actions("U-CLICK", "open_portal", campaign.id)
    await slack_service.handle_interaction(db, client, payload)
    assert client.responses == []


# --- endpoint --------------------------------------------------------------


@pytest.fixture
def slack_configured(monkeypatch):
    monkeypatch.setattr(settings, "SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setattr(settings, "SLACK_SIGNING_SECRET", "shh")


async def test_interactions_rejects_bad_signature(client, slack_configured):
    body = urlencode({"payload": json.dumps({"type": "block_actions"})}).encode()
    ts = str(int(datetime.now(UTC).timestamp()))
    resp = await client.post(
        "/v1/slack/interactions",
        content=body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "X-Slack-Request-Timestamp": ts,
            "X-Slack-Signature": "v0=deadbeef",
        },
    )
    assert resp.status_code == 401


async def test_interactions_503_when_not_configured(client, monkeypatch):
    monkeypatch.setattr(settings, "SLACK_BOT_TOKEN", None)
    monkeypatch.setattr(settings, "SLACK_SIGNING_SECRET", None)
    resp = await client.post("/v1/slack/interactions", content=b"payload=%7B%7D")
    assert resp.status_code == 503


async def test_interactions_enqueues_and_acks_fast(client, slack_configured, enqueued):
    # A valid signature acks 200 immediately and enqueues the handling job; no
    # approval work or outbound Slack call happens in the request path.
    payload = {
        "type": "block_actions",
        "user": {"id": "U-NOBODY"},
        "response_url": "https://hooks.slack.test/x",
        "actions": [{"action_id": "campaign_approve_all", "value": str(uuid.uuid4())}],
    }
    body = urlencode({"payload": json.dumps(payload)}).encode()
    ts = str(int(datetime.now(UTC).timestamp()))
    resp = await client.post(
        "/v1/slack/interactions",
        content=body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "X-Slack-Request-Timestamp": ts,
            "X-Slack-Signature": _sign("shh", ts, body),
        },
    )
    assert resp.status_code == 200
    jobs = [c for c in enqueued if c[0] == "handle_slack_interaction"]
    assert len(jobs) == 1
    # The parsed payload is handed to the worker verbatim.
    assert jobs[0][1][0]["actions"][0]["action_id"] == "campaign_approve_all"
