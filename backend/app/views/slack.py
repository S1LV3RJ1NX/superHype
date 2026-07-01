"""Slack router: the interactivity endpoint Slack calls when a button is clicked.

Slack signs the request, so the raw body is read here and passed through to the
controller for signature verification before anything is parsed or trusted.
"""

from fastapi import APIRouter, Request, Response

from app.controllers import slack_controller

router = APIRouter(tags=["slack"])


@router.post("/v1/slack/interactions")
async def slack_interactions(request: Request) -> Response:
    raw = await request.body()
    return await slack_controller.handle_interaction(
        raw=raw,
        timestamp=request.headers.get("X-Slack-Request-Timestamp"),
        signature=request.headers.get("X-Slack-Signature"),
    )
