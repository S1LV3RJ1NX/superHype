"""Auth, onboarding, and RBAC dependencies.

get_current_user extracts the bearer JWT, decodes it, loads the user from the
database, and verifies the user is active. require_onboarded additionally
demands a finished onboarding. require_role is a dependency factory that gates
on cumulative roles, and builds on require_onboarded because every role-gated
action is a real action in the product.
"""

from collections.abc import Awaitable, Callable

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import TokenPayload, decode_access_token
from app.db.session import get_db
from app.models.user import User
from app.repositories.social_account_repo import social_account_repo
from app.repositories.user_repo import user_repo

_bearer = HTTPBearer()

# The frontend keys off this code to bounce the user back into the wizard, so
# it is part of the API contract rather than an opaque message.
ONBOARDING_INCOMPLETE_CODE = "onboarding_incomplete"


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    payload: TokenPayload = decode_access_token(credentials.credentials)
    user = await user_repo.get(db, payload.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="Invalid or inactive user.")
    return user


def _onboarding_error(step: int, message: str) -> HTTPException:
    return HTTPException(
        status_code=403,
        detail={
            "code": ONBOARDING_INCOMPLETE_CODE,
            "step": step,
            "message": message,
        },
    )


async def require_onboarded(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Reject users who signed in but never finished onboarding.

    A row exists from the moment Google login succeeds, so authentication alone
    says nothing about whether the person can be acted on: they publish and
    engage through their own LinkedIn account, and their team drives the persona
    used for generation. This mirrors the frontend gate in ProtectedRoute so the
    two cannot drift, including treating a stale LinkedIn account as onboarded
    (stale means reconnect, not start over). Onboarding routes themselves
    (users/me, the team list, connections) stay on get_current_user.
    """
    if user.team_id is None:
        raise _onboarding_error(1, "Pick your team to finish setting up super-hype.")
    account = await social_account_repo.get_by_user(db, user.id, "linkedin")
    if account is None:
        raise _onboarding_error(
            2, "Connect your LinkedIn account to finish setting up super-hype."
        )
    return user


ROLE_HIERARCHY = {"viewer": 0, "editor": 1, "admin": 2}


def require_role(*roles: str) -> Callable[..., Awaitable[User]]:
    min_level = min(ROLE_HIERARCHY.get(r, 0) for r in roles)

    async def _dep(user: User = Depends(require_onboarded)) -> User:
        user_level = ROLE_HIERARCHY.get(user.role, -1)
        if user_level < min_level:
            raise HTTPException(
                status_code=403, detail="You do not have access to this action."
            )
        return user

    return _dep
