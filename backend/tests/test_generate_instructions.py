"""Tests for POST /v1/skills/generate-instructions."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.asyncio


def _mock_llm_response(content: str) -> MagicMock:
    msg = MagicMock()
    msg.content = content
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp


async def test_generate_instructions_returns_text(client, as_role):
    instructions = "You are a witty LinkedIn ghost-writer..."
    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(
        return_value=_mock_llm_response(instructions)
    )

    async with as_role("editor"):
        with patch(
            "app.services.generation_service.get_llm_client",
            return_value=mock_client,
        ):
            resp = await client.post(
                "/v1/skills/generate-instructions",
                json={"description": "Fun product launch posts"},
            )

    assert resp.status_code == 200
    assert resp.json()["instructions"] == instructions


async def test_generate_instructions_viewer_forbidden(client, as_role):
    async with as_role("viewer"):
        resp = await client.post(
            "/v1/skills/generate-instructions",
            json={"description": "test"},
        )
    assert resp.status_code == 403


async def test_generate_instructions_handles_gateway_error(client, as_role):
    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(side_effect=RuntimeError("boom"))

    async with as_role("editor"):
        with patch(
            "app.services.generation_service.get_llm_client",
            return_value=mock_client,
        ):
            resp = await client.post(
                "/v1/skills/generate-instructions",
                json={"description": "test"},
            )
    assert resp.status_code == 502
    assert "gateway" not in resp.json()["detail"].lower()
