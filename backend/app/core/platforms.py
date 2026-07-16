"""Supported social platforms and their human-readable labels.

One tiny module so the worker, services, and Slack copy all name platforms the
same way without each keeping its own mapping.
"""

SUPPORTED_PLATFORMS: tuple[str, ...] = ("linkedin", "x")

_LABELS = {"linkedin": "LinkedIn", "x": "X"}


def platform_label(platform: str | None) -> str:
    """Human-readable platform name for messages and UI copy."""
    return _LABELS.get(platform or "linkedin", "LinkedIn")
