"""Smoke test: call the real LLM gateway with the default skill and a sample brief.

Run with: uv run python -m scripts.smoke_generation
"""

import asyncio
import json

from app.schemas.generation import GenerationBrief, RosterEntry
from app.services.generation_service import generate


async def main() -> None:
    from sqlalchemy import select

    from app.db.session import async_session_factory
    from app.models.writing_skill import WritingSkill

    async with async_session_factory() as db:
        skill = (
            await db.execute(
                select(WritingSkill).where(WritingSkill.is_default.is_(True))
            )
        ).scalar_one_or_none()

    if skill is None:
        print("No default skill found. Run `uv run python -m app.seed` first.")
        return

    brief = GenerationBrief(
        title="Super-Hype v0.2 Launch",
        raw_brief=(
            "We just shipped v0.2 of super-hype, our internal employee-advocacy "
            "tool. It now supports LinkedIn OAuth connection and writing-skill "
            "management. The team worked hard on encrypted token storage and "
            "Redis-bound CSRF state."
        ),
        link="https://github.com/example/super-hype",
        roster=[
            RosterEntry(name="Prathamesh", role="Founder & FDE", language="en"),
            RosterEntry(name="Raj", role="Platform Engineer", language="hi"),
        ],
    )

    print(f"Using skill: {skill.name}")
    print(f"Model: {skill.model or 'from LLM_MODEL_NAME env'}")
    print(f"Brief: {brief.title}")
    print("Calling gateway...")

    result = await generate(skill, brief)
    print("\nGeneration succeeded!\n")
    print(json.dumps(result.model_dump(), indent=2))


if __name__ == "__main__":
    asyncio.run(main())
