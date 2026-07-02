"""Slack bundled-approval service.

One Slack card per participant per campaign: every action a person owns (self
post, reshare, comment, like, self-comment) is listed together with a single
Approve all / Skip all control, so they settle everything in one click instead of
one card per action. Interactions come back through ``handle_interaction``, which
resolves the clicker to an app user and runs the same ``approval_service`` the web
portal uses. Slack is strictly additive: the portal flow works unchanged whether
or not Slack is configured.
"""

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.integrations.slack import SlackClient, SlackError
from app.logger import get_logger
from app.models.campaign import Campaign
from app.models.post import Post
from app.models.slack_identity import SlackIdentity
from app.models.user import User
from app.repositories.post_repo import post_repo
from app.repositories.slack_identity_repo import slack_identity_repo
from app.repositories.user_repo import user_repo
from app.services import approval_service
from app.services.approval_service import ApprovalError, ReconnectRequiredError

log = get_logger(__name__)

# What each post row means to the person, in plain language for the DM card.
_ACTION_LABELS = {
    "post": "Publish your post",
    "repost_comment": "Reshare with your comment",
    "comment": "Comment on a teammate's post",
    "like": "Like a teammate's post",
    "self_comment": "Add the link as a comment on your post",
}

# Statuses a person can still act on, per operation. Approve reuses the states
# approval_service accepts; skip additionally settles an assisted ask in flight.
_APPROVE_STATUSES = ("pending", "scheduled", "failed")
_SKIP_STATUSES = ("pending", "scheduled", "action_required", "failed")
# The assisted engagement bundle only touches asks the worker has already handed
# to the person (comment/like/self-comment awaiting a manual action).
_ENGAGE_STATUSES = ("action_required",)

_APPROVE_ACTION_ID = "campaign_approve_all"
_SKIP_ACTION_ID = "campaign_skip_all"
_ACK_ACTION_ID = "engagement_ack_all"
_ENGAGE_SKIP_ACTION_ID = "engagement_skip_all"

# action_id -> (approval op, statuses to gather for that op). One table drives
# both bundle cards (approve/skip at launch, ack/skip for assisted engagements).
_INTERACTION_OPS: dict[str, tuple[str, tuple[str, ...]]] = {
    _APPROVE_ACTION_ID: ("approve", _APPROVE_STATUSES),
    _SKIP_ACTION_ID: ("skip", _SKIP_STATUSES),
    _ACK_ACTION_ID: ("ack", _ENGAGE_STATUSES),
    _ENGAGE_SKIP_ACTION_ID: ("skip", _ENGAGE_STATUSES),
}


def _result_message(op: str, n: int) -> str:
    if op == "approve":
        return f"Approved {n} action(s). Thanks for keeping the campaign moving."
    if op == "ack":
        return f"Marked {n} action(s) done. Thanks for keeping the campaign moving."
    return f"Skipped {n} action(s)."


async def resolve_identity(
    db: AsyncSession, client: SlackClient, user: User
) -> SlackIdentity | None:
    """Return the user's Slack identity, resolving and caching it on first use.

    A cache hit skips Slack entirely. On a miss we look the person up by their
    company email and open a DM channel, then store both so later sends are one
    call. Returns None when Slack has no matching member (nothing to DM).
    """
    identity = await slack_identity_repo.get_by_user(db, user.id)
    if identity is not None:
        return identity
    if not user.email:
        return None
    slack_user_id = await client.lookup_user_by_email(user.email)
    if slack_user_id is None:
        return None
    try:
        channel = await client.open_dm(slack_user_id)
    except SlackError:
        channel = None
    identity = await slack_identity_repo.upsert(
        db,
        user_id=user.id,
        slack_user_id=slack_user_id,
        slack_dm_channel=channel,
    )
    await db.commit()
    return identity


def _summarize(posts: list[Post]) -> list[str]:
    """Ordered, de-duplicated "N x label" lines describing the bundle."""
    counts: dict[str, int] = {}
    order: list[str] = []
    for post in posts:
        label = _ACTION_LABELS.get(post.action, post.action)
        if label not in counts:
            order.append(label)
        counts[label] = counts.get(label, 0) + 1
    lines = []
    for label in order:
        n = counts[label]
        lines.append(f"- {label}" + (f" (x{n})" if n > 1 else ""))
    return lines


def _bundle_blocks(
    campaign: Campaign, posts: list[Post]
) -> tuple[list[dict[str, Any]], str]:
    """Build the Block Kit payload (and text fallback) for the bundled ask."""
    portal_url = f"{settings.FRONTEND_URL}/app/campaigns/{campaign.id}"
    summary = "\n".join(_summarize(posts))
    text = f"You have {len(posts)} LinkedIn action(s) for {campaign.title}"
    blocks: list[dict[str, Any]] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "Your LinkedIn actions"},
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*{campaign.title}*\nApprove everything below in one click, "
                    f"or open the portal to review each item.\n\n{summary}"
                ),
            },
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Approve all"},
                    "style": "primary",
                    "action_id": _APPROVE_ACTION_ID,
                    "value": str(campaign.id),
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Skip all"},
                    "action_id": _SKIP_ACTION_ID,
                    "value": str(campaign.id),
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Open portal"},
                    "url": portal_url,
                    "action_id": "open_portal",
                },
            ],
        },
    ]
    return blocks, text


async def notify_participant(
    db: AsyncSession,
    client: SlackClient,
    campaign: Campaign,
    user: User,
    posts: list[Post],
) -> None:
    """DM one participant the bundled card for all their actions in a campaign."""
    if not posts:
        return
    identity = await resolve_identity(db, client, user)
    if identity is None:
        log.info(
            "slack.notify_participant.no_identity",
            user_id=str(user.id),
            campaign_id=str(campaign.id),
        )
        return
    channel = identity.slack_dm_channel or identity.slack_user_id
    blocks, text = _bundle_blocks(campaign, posts)
    try:
        await client.post_message(channel, text=text, blocks=blocks)
    except SlackError as exc:
        log.warning(
            "slack.notify_participant.send_failed",
            user_id=str(user.id),
            error=str(exc),
        )


def _target_key(post: Post) -> str:
    """Stable key for the post a person acts on, so like + comment collapse.

    Like and comment on the same teammate's post share a target (and deep link),
    so they group into one entry; a self-comment targets the person's own post and
    naturally lands in its own group.
    """
    if post.target_post_id is not None:
        return f"p:{post.target_post_id}"
    if post.target_external_id:
        return f"u:{post.target_external_id}"
    return f"e:{post.engagement_url or post.id}"


def _group_label(actions: set[str]) -> str:
    """Human label for one grouped target, combining like + comment when both."""
    if "self_comment" in actions:
        return "Add your link as a comment on your post"
    if "like" in actions and "comment" in actions:
        return "Like and comment on this teammate's post"
    if "comment" in actions:
        return "Comment on this teammate's post"
    if "like" in actions:
        return "Like this teammate's post"
    return "Engage on this post"


def _engagement_blocks(
    campaign: Campaign, posts: list[Post]
) -> tuple[list[dict[str, Any]], str, list[str]]:
    """Block Kit for the assisted engagement bundle (comment/like/self-comment).

    Asks are grouped by the post they act on, so a like and a comment on the same
    teammate's post are one entry (matching the portal's combined card): a deep
    link to the post plus, when there is a comment, the suggested text to paste.
    One Mark all done / Skip all pair settles every listed ask.

    Also returns the ordered suggested comments so the caller can post each as its
    own message. Slack's one-tap Copy on a code block is desktop only, so on mobile
    a standalone message is what a person long-presses to "Copy text".
    """
    # Preserve first-seen order while collapsing same-target asks into one group.
    groups: dict[str, list[Post]] = {}
    for post in posts:
        groups.setdefault(_target_key(post), []).append(post)

    text = f"You have {len(groups)} LinkedIn engagement(s) to do for {campaign.title}"
    blocks: list[dict[str, Any]] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "Time to comment and like"},
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*{campaign.title}*\nDo these on LinkedIn, then mark them done "
                    "here:"
                ),
            },
        },
    ]
    comment_texts: list[str] = []
    for group in groups.values():
        actions = {p.action for p in group}
        line = f"*{_group_label(actions)}*"
        url = next((p.engagement_url for p in group if p.engagement_url), None)
        if url:
            line += f" - <{url}|open the post>"
        # The comment text (from the comment or self-comment in the group) is not
        # inlined here: it is sent as its own message (below) so it copies cleanly
        # on both mobile and desktop. The card just points to that message.
        body = next(
            (
                p.body
                for p in group
                if p.action in ("comment", "self_comment") and p.body
            ),
            None,
        )
        if body:
            comment_texts.append(body)
            line += (
                "\n_Copy the comment from the next message and paste it on the post._"
            )
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": line}})
    if comment_texts:
        blocks.append(
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": (
                            "The suggested comment is in the message below. Long-press "
                            "(mobile) or click (desktop) it to copy."
                        ),
                    }
                ],
            }
        )
    blocks.append(
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Mark all done"},
                    "style": "primary",
                    "action_id": _ACK_ACTION_ID,
                    "value": str(campaign.id),
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Skip all"},
                    "action_id": _ENGAGE_SKIP_ACTION_ID,
                    "value": str(campaign.id),
                },
            ],
        }
    )
    return blocks, text, comment_texts


async def notify_engagements(
    db: AsyncSession,
    client: SlackClient,
    campaign: Campaign,
    user: User,
    posts: list[Post],
) -> None:
    """DM one participant the bundled assisted-engagement ask (Mark all done)."""
    if not posts:
        return
    identity = await resolve_identity(db, client, user)
    if identity is None:
        log.info(
            "slack.notify_engagements.no_identity",
            user_id=str(user.id),
            campaign_id=str(campaign.id),
        )
        return
    channel = identity.slack_dm_channel or identity.slack_user_id
    blocks, text, comment_texts = _engagement_blocks(campaign, posts)
    try:
        await client.post_message(channel, text=text, blocks=blocks)
        # Each suggested comment as its own plain message: on mobile a person
        # long-presses it and taps "Copy text" (the code block's Copy button is
        # desktop only). No blocks, so nothing but the comment gets copied.
        for comment in comment_texts:
            await client.post_message(channel, text=comment)
    except SlackError as exc:
        log.warning(
            "slack.notify_engagements.send_failed",
            user_id=str(user.id),
            error=str(exc),
        )


async def notify_reconnect(db: AsyncSession, client: SlackClient, user: User) -> None:
    """DM a person that their LinkedIn token went stale, with a reconnect link."""
    identity = await resolve_identity(db, client, user)
    if identity is None:
        log.info("slack.notify_reconnect.no_identity", user_id=str(user.id))
        return
    channel = identity.slack_dm_channel or identity.slack_user_id
    reconnect_url = f"{settings.FRONTEND_URL}/app/connections"
    text = (
        "Your LinkedIn connection expired, so super-hype cannot publish on your "
        f"behalf until you reconnect: {reconnect_url}"
    )
    try:
        await client.post_message(channel, text=text)
    except SlackError as exc:
        log.warning(
            "slack.notify_reconnect.send_failed",
            user_id=str(user.id),
            error=str(exc),
        )


async def _safe_respond(
    client: SlackClient, response_url: str | None, text: str
) -> None:
    """Best-effort update of the original card; a failed reply is not fatal."""
    if not response_url:
        return
    try:
        await client.respond(response_url, {"replace_original": True, "text": text})
    except Exception as exc:
        log.warning("slack.respond_failed", error=str(exc))


async def handle_interaction(
    db: AsyncSession, client: SlackClient, payload: dict[str, Any]
) -> None:
    """Run a bundle action (Approve/Skip all, Mark all done) from an interaction.

    The payload is already signature-verified by the view. We map the Slack user
    back to an app user, gather that person's actionable posts in the campaign,
    and run them through ``approval_service`` (the same path the portal uses), then
    replace the card with the outcome. The action_id decides the operation and
    which post states to gather (see ``_INTERACTION_OPS``).
    """
    if payload.get("type") != "block_actions":
        return
    actions = payload.get("actions") or []
    if not actions:
        return
    action = actions[0]
    action_id = action.get("action_id", "")
    mapping = _INTERACTION_OPS.get(action_id)
    if mapping is None:
        return  # e.g. the "Open portal" link button carries no server action.
    op, statuses = mapping
    response_url = payload.get("response_url")

    slack_user_id = (payload.get("user") or {}).get("id")
    if not slack_user_id:
        return
    identity = await slack_identity_repo.get_by_slack_user(db, slack_user_id)
    if identity is None:
        await _safe_respond(
            client,
            response_url,
            "We could not match your Slack account to super-hype. "
            "Please act from the portal instead.",
        )
        return
    user = await user_repo.get(db, identity.user_id)
    if user is None:
        await _safe_respond(
            client, response_url, "Your super-hype account was not found."
        )
        return

    try:
        campaign_id = uuid.UUID(str(action.get("value")))
    except (TypeError, ValueError):
        return

    posts = await post_repo.list_for_campaign_user(
        db, campaign_id, user.id, statuses=statuses
    )
    if not posts:
        await _safe_respond(
            client, response_url, "You're all set. Nothing here needs your action."
        )
        return

    post_ids = [p.id for p in posts]
    try:
        settled = await approval_service.batch(db, op=op, post_ids=post_ids, actor=user)
    except ReconnectRequiredError:
        reconnect_url = f"{settings.FRONTEND_URL}/app/connections"
        await _safe_respond(
            client,
            response_url,
            "Your LinkedIn connection needs to be refreshed before we can "
            f"publish. Reconnect here: {reconnect_url}",
        )
        return
    except ApprovalError as exc:
        await _safe_respond(client, response_url, f"Could not {op}: {exc}")
        return

    await _safe_respond(client, response_url, _result_message(op, len(settled)))
