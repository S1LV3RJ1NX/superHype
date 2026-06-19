"""Tests for the generation service. The OpenAI client is mocked; no real calls."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.generation_service import (
    GenerationError,
    generate_interactions,
    generate_variations,
)

pytestmark = pytest.mark.asyncio


def _mock_completion(content: str) -> MagicMock:
    choice = MagicMock()
    choice.message.content = content
    resp = MagicMock()
    resp.choices = [choice]
    return resp


def _client(content: str) -> AsyncMock:
    client = AsyncMock()
    client.chat.completions.create = AsyncMock(return_value=_mock_completion(content))
    return client


async def test_generate_variations_enforces_count():
    payload = json.dumps({"variations": ["one", "two", "three", "four"]})
    with patch(
        "app.services.generation_service.get_llm_client", return_value=_client(payload)
    ):
        out = await generate_variations("seed post", 3)
    assert out == ["one", "two", "three"]


async def test_generate_variations_pads_when_too_few():
    payload = json.dumps({"variations": ["a", "b"]})
    with patch(
        "app.services.generation_service.get_llm_client", return_value=_client(payload)
    ):
        out = await generate_variations("seed", 3)
    assert len(out) == 3
    assert set(out) <= {"a", "b"}


async def test_generate_variations_fenced_json():
    payload = "```json\n" + json.dumps({"variations": ["x", "y"]}) + "\n```"
    with patch(
        "app.services.generation_service.get_llm_client", return_value=_client(payload)
    ):
        out = await generate_variations("seed", 2)
    assert out == ["x", "y"]


async def test_generate_variations_non_json_raises():
    with (
        patch(
            "app.services.generation_service.get_llm_client",
            return_value=_client("not json"),
        ),
        pytest.raises(GenerationError, match="non-JSON"),
    ):
        await generate_variations("seed", 2)


async def test_generate_interactions_indexed_and_likes_empty():
    items = [
        {"action": "comment", "angle": "supportive"},
        {"action": "like"},
        {"action": "repost_comment", "angle": "amplify"},
    ]
    payload = json.dumps({"texts": ["nice work", "resharing this"]})
    with patch(
        "app.services.generation_service.get_llm_client", return_value=_client(payload)
    ):
        out = await generate_interactions("target", items)
    assert out == ["nice work", "", "resharing this"]


async def test_generate_interactions_all_likes_skips_llm():
    items = [{"action": "like"}, {"action": "like"}]
    # No client patch needed: all-likes must not call the gateway.
    out = await generate_interactions("target", items)
    assert out == ["", ""]


async def test_generate_interactions_bad_contract_raises():
    items = [{"action": "comment", "angle": "x"}]
    payload = json.dumps({"wrong_key": []})
    with (
        patch(
            "app.services.generation_service.get_llm_client",
            return_value=_client(payload),
        ),
        pytest.raises(GenerationError, match="does not match"),
    ):
        await generate_interactions("target", items)
