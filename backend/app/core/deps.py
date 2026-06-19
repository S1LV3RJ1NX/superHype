"""Auth and RBAC dependencies.

Phase 0 stub: there is no real authentication yet, so get_current_user returns a
placeholder admin and require_role is a passthrough. This lets the reference
campaigns route resolve and establishes the dependency shape that Phase 1 fills in
(decode the bearer JWT, load the active user, enforce roles).
"""

import uuid
from collections.abc import Awaitable, Callable

from app.models.user import User

_PLACEHOLDER_USER = User(
    id=uuid.UUID("00000000-0000-0000-0000-000000000000"),
    email="placeholder@local",
    name="Placeholder Admin",
    role="admin",
    is_active=True,
)


async def get_current_user() -> User:
    """Return the authenticated user. Phase 0 returns a placeholder admin."""
    return _PLACEHOLDER_USER


def require_role(*roles: str) -> Callable[..., Awaitable[User]]:
    """Coarse role gate. Phase 0 passthrough; Phase 1 enforces the roles."""

    async def _dep() -> User:
        return await get_current_user()

    return _dep
