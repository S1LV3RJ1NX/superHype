"""OpenAI-compatible async client pointed at the LLM gateway.

All generation calls go through this client. The gateway URL, key, and model
come from settings.
"""

from openai import AsyncOpenAI

from app.config import settings


def get_llm_client() -> AsyncOpenAI:
    """Return an async OpenAI client configured for the LLM gateway."""
    return AsyncOpenAI(
        base_url=settings.LLM_GATEWAY_URL,
        api_key=settings.LLM_API_KEY,
    )
