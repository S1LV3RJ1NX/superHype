"""Whether a person's actions are auto-approved or wait for their approval.

A dependency-light predicate shared by the user controller, the approval
service, and the worker, so the flag and the consent are checked one way.
"""

from app.config import settings
from app.models.user import User


def auto_approve_available() -> bool:
    """True when the deployment offers auto-approve (MANUAL_APPROVAL_ONLY off)."""
    return not settings.MANUAL_APPROVAL_ONLY


def auto_approves(user: User) -> bool:
    """True when this person's actions should be approved automatically.

    Needs both the deployment to offer it and the person's own opt-in; either
    one missing means every action waits for them to approve it.
    """
    return auto_approve_available() and user.auto_approve_consented_at is not None
