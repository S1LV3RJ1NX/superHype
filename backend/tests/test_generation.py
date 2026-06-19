"""Tests for the generation service.

The OpenAI client is mocked; no real gateway calls.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.writing_skill import WritingSkill
from app.schemas.generation import GenerationBrief, GenerationResult, RosterEntry
from app.services.generation_service import (
    _OUTPUT_CONTRACT,
    GenerationError,
    generate,
)

_SAMPLE_BRIEF = GenerationBrief(
    title="Test Launch",
    raw_brief="We shipped a feature.",
    roster=[RosterEntry(name="Alice", role="Engineer")],
)


def _make_skill(model: str | None = None) -> WritingSkill:
    return WritingSkill(name="Test Skill", instructions="Generate posts.", model=model)


_VALID_OUTPUT = {
    "campaign": "Test Launch",
    "assumptions": "none",
    "hero_post": {
        "account": "alice",
        "text": "We shipped it!",
        "link_placement": "first_comment",
        "first_comment": "Link: https://example.com",
        "hashtags": ["#launch"],
    },
    "variants": [
        {
            "person": "Alice",
            "role": "Engineer",
            "action": "post",
            "angle": "technical",
            "text_en": "From the eng side...",
        }
    ],
    "comments": [
        {
            "person": "Alice",
            "on": "hero_post",
            "text_en": "The migration was tricky.",
        }
    ],
}


def _mock_completion(content: str) -> MagicMock:
    choice = MagicMock()
    choice.message.content = content
    resp = MagicMock()
    resp.choices = [choice]
    return resp


@pytest.mark.asyncio
async def test_valid_json_parses():
    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(
        return_value=_mock_completion(json.dumps(_VALID_OUTPUT))
    )

    with patch(
        "app.services.generation_service.get_llm_client", return_value=mock_client
    ):
        result = await generate(_make_skill(), _SAMPLE_BRIEF)

    assert isinstance(result, GenerationResult)
    assert result.hero_post.text == "We shipped it!"
    assert len(result.variants) == 1
    assert len(result.comments) == 1


@pytest.mark.asyncio
async def test_fenced_json_parses():
    fenced = "```json\n" + json.dumps(_VALID_OUTPUT) + "\n```"
    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(
        return_value=_mock_completion(fenced)
    )

    with patch(
        "app.services.generation_service.get_llm_client", return_value=mock_client
    ):
        result = await generate(_make_skill(), _SAMPLE_BRIEF)

    assert isinstance(result, GenerationResult)


@pytest.mark.asyncio
async def test_non_json_raises_generation_error():
    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(
        return_value=_mock_completion("This is not JSON at all.")
    )

    with (
        patch(
            "app.services.generation_service.get_llm_client",
            return_value=mock_client,
        ),
        pytest.raises(GenerationError, match="non-JSON"),
    ):
        await generate(_make_skill(), _SAMPLE_BRIEF)


@pytest.mark.asyncio
async def test_missing_keys_raises_generation_error():
    incomplete = json.dumps({"campaign": "x"})
    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(
        return_value=_mock_completion(incomplete)
    )

    with (
        patch(
            "app.services.generation_service.get_llm_client",
            return_value=mock_client,
        ),
        pytest.raises(GenerationError, match="does not match"),
    ):
        await generate(_make_skill(), _SAMPLE_BRIEF)


@pytest.mark.asyncio
async def test_uses_llm_model_name_from_settings():
    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(
        return_value=_mock_completion(json.dumps(_VALID_OUTPUT))
    )

    with patch(
        "app.services.generation_service.get_llm_client", return_value=mock_client
    ):
        await generate(_make_skill(), _SAMPLE_BRIEF)

    call_kwargs = mock_client.chat.completions.create.call_args
    from app.config import settings

    expected_model = settings.LLM_MODEL_NAME
    assert (
        call_kwargs.kwargs.get("model") == expected_model
        or call_kwargs[1].get("model") == expected_model
    )


@pytest.mark.asyncio
async def test_output_contract_injected_into_system_prompt():
    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(
        return_value=_mock_completion(json.dumps(_VALID_OUTPUT))
    )

    skill = _make_skill()
    with patch(
        "app.services.generation_service.get_llm_client", return_value=mock_client
    ):
        await generate(skill, _SAMPLE_BRIEF)

    call_kwargs = mock_client.chat.completions.create.call_args
    messages = call_kwargs.kwargs.get("messages") or call_kwargs[1].get("messages")
    system_content = messages[0]["content"]
    assert system_content.startswith(skill.instructions)
    assert system_content.endswith(_OUTPUT_CONTRACT)
    assert _OUTPUT_CONTRACT in system_content
