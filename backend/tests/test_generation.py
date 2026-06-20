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
    comment = (
        "This matches what we saw building inference infra, the idle cost is the "
        "real leak here."
    )
    reshare = (
        "Resharing because the cold start numbers finally make scale to zero safe "
        "for real production traffic."
    )
    payload = json.dumps({"texts": [comment, reshare]})
    with patch(
        "app.services.generation_service.get_llm_client", return_value=_client(payload)
    ):
        out = await generate_interactions("target", items)
    assert out == [comment, "", reshare]


async def test_generate_interactions_low_quality_fails_after_retry():
    items = [{"action": "comment", "angle": "x"}]
    payload = json.dumps({"texts": ["Great post!"]})
    with (
        patch(
            "app.services.generation_service.get_llm_client",
            return_value=_client(payload),
        ),
        pytest.raises(GenerationError, match="low-quality"),
    ):
        await generate_interactions("target", items)


async def test_generate_interactions_banned_phrase_rejected():
    items = [{"action": "comment", "angle": "x"}]
    # Long enough to pass the word floor, but contains a banned buzzword.
    text = (
        "We are so thrilled to share this incredible game-changer that will "
        "absolutely transform everything for everyone now"
    )
    payload = json.dumps({"texts": [text]})
    with (
        patch(
            "app.services.generation_service.get_llm_client",
            return_value=_client(payload),
        ),
        pytest.raises(GenerationError, match="low-quality"),
    ):
        await generate_interactions("target", items)


async def test_generate_interactions_regenerates_then_succeeds():
    items = [{"action": "comment", "angle": "x"}]
    good = (
        "Curious how you handled cold starts under load; we hit a wall around the "
        "eight second mark too."
    )
    client = AsyncMock()
    client.chat.completions.create = AsyncMock(
        side_effect=[
            _mock_completion(json.dumps({"texts": ["Love this"]})),
            _mock_completion(json.dumps({"texts": [good]})),
        ]
    )
    with patch("app.services.generation_service.get_llm_client", return_value=client):
        out = await generate_interactions("target", items)
    assert out == [good]
    assert client.chat.completions.create.await_count == 2


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
