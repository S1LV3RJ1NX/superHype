"""Auth and RBAC dependencies.

get_current_user extracts the bearer JWT, decodes it, loads the user from the
database, and verifies the user is active. require_role is a dependency factory
that gates on cumulative roles.
"""

from collections.abc import Awaitable, Callable

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import TokenPayload, decode_access_token
from app.db.session import get_db
from app.models.user import User
from app.repositories.user_repo import user_repo

_bearer = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    payload: TokenPayload = decode_access_token(credentials.credentials)
    user = await user_repo.get(db, payload.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="Invalid or inactive user.")
    return user


ROLE_HIERARCHY = {"viewer": 0, "editor": 1, "admin": 2}


def require_role(*roles: str) -> Callable[..., Awaitable[User]]:
    min_level = min(ROLE_HIERARCHY.get(r, 0) for r in roles)

    async def _dep(user: User = Depends(get_current_user)) -> User:
        user_level = ROLE_HIERARCHY.get(user.role, -1)
        if user_level < min_level:
            raise HTTPException(
                status_code=403, detail="You do not have access to this action."
            )
        return user

    return _dep
