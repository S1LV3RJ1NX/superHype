"""Slack controller: authenticate and dispatch inbound Slack interactions.

Verifies the request signature over the raw body (the one place that must see the
unparsed bytes), extracts the interaction payload, and enqueues a job to run it.
Kept thin: no business logic, no DB, no outbound calls in the request. The actual
approval work and the card update happen in the worker, so we always ack Slack
inside its 3s window.
"""

import json
from urllib.parse import parse_qs

from fastapi import HTTPException, Response

from app.config import settings
from app.integrations import slack as slack_integration
from app.workers import queue


async def handle_interaction(
    *,
    raw: bytes,
    timestamp: str | None,
    signature: str | None,
) -> Response:
    if not slack_integration.is_configured():
        raise HTTPException(503, "Slack is not configured.")
    if not slack_integration.verify_signature(
        signing_secret=settings.SLACK_SIGNING_SECRET,
        timestamp=timestamp,
        body=raw,
        signature=signature,
    ):
        raise HTTPException(401, "Invalid Slack signature.")

    # Slack posts interactions as x-www-form-urlencoded with a single JSON field.
    form = parse_qs(raw.decode("utf-8"))
    payload_values = form.get("payload")
    if not payload_values:
        raise HTTPException(400, "Missing interaction payload.")
    try:
        payload = json.loads(payload_values[0])
    except json.JSONDecodeError as exc:
        raise HTTPException(400, "Malformed interaction payload.") from exc

    # Enqueue and ack fast with an empty 200; the worker runs the approval and
    # updates the card via response_url (valid for 30 minutes).
    await queue.enqueue_job("handle_slack_interaction", payload)
    return Response(status_code=200)
