"""Tests for POST /v1/skills/{id}/test."""

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.asyncio

VALID_LLM_OUTPUT = json.dumps(
    {
        "campaign": "test",
        "assumptions": "none",
        "hero_post": {
            "account": "Founder",
            "platform": "linkedin",
            "text": "Hello world",
            "link_placement": "first_comment",
            "first_comment": "",
            "hashtags": [],
        },
        "variants": [
            {
                "person": "Alex",
                "role": "Engineer",
                "platform": "linkedin",
                "action": "post",
                "angle": "tech",
                "text_en": "Great feature",
                "text_native": "",
                "native_language": "",
            }
        ],
        "comments": [],
    }
)


def _mock_llm_response(content: str) -> MagicMock:
    msg = MagicMock()
    msg.content = content
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp


async def test_test_skill_returns_output(client, as_role, db):
    from app.models.writing_skill import WritingSkill

    skill = WritingSkill(name="Test Skill", instructions="write posts", status="draft")
    db.add(skill)
    await db.commit()
    await db.refresh(skill)

    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(
        return_value=_mock_llm_response(VALID_LLM_OUTPUT)
    )

    async with as_role("editor"):
        with patch(
            "app.services.generation_service.get_llm_client",
            return_value=mock_client,
        ):
            resp = await client.post(
                f"/v1/skills/{skill.id}/test",
                json={
                    "title": "Launch",
                    "raw_brief": "We shipped a feature",
                },
            )

    assert resp.status_code == 200
    data = resp.json()["output"]
    assert data["campaign"] == "test"
    assert data["hero_post"]["text"] == "Hello world"
    assert len(data["variants"]) == 1


async def test_test_skill_viewer_forbidden(client, as_role, db):
    from app.models.writing_skill import WritingSkill

    skill = WritingSkill(name="Viewer Test", instructions="write posts", status="draft")
    db.add(skill)
    await db.commit()
    await db.refresh(skill)

    async with as_role("viewer"):
        resp = await client.post(
            f"/v1/skills/{skill.id}/test",
            json={"title": "Launch", "raw_brief": "brief"},
        )
    assert resp.status_code == 403


async def test_test_skill_not_found(client, as_role):
    fake_id = uuid.uuid4()
    async with as_role("editor"):
        resp = await client.post(
            f"/v1/skills/{fake_id}/test",
            json={"title": "Launch", "raw_brief": "brief"},
        )
    assert resp.status_code == 404


async def test_test_skill_generation_error_returns_502(client, as_role, db):
    from app.models.writing_skill import WritingSkill

    skill = WritingSkill(name="Error Skill", instructions="write posts", status="draft")
    db.add(skill)
    await db.commit()
    await db.refresh(skill)

    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(
        side_effect=RuntimeError("gateway down")
    )

    async with as_role("editor"):
        with patch(
            "app.services.generation_service.get_llm_client",
            return_value=mock_client,
        ):
            resp = await client.post(
                f"/v1/skills/{skill.id}/test",
                json={"title": "Launch", "raw_brief": "brief"},
            )

    assert resp.status_code == 502
    assert "gateway" not in resp.json()["detail"].lower()
