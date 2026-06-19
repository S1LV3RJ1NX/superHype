"""SQLAlchemy models. Importing this package registers every table on Base.metadata."""

from app.models.audit_log import AuditLog
from app.models.campaign import Campaign
from app.models.post import Post
from app.models.slack_identity import SlackIdentity
from app.models.social_account import SocialAccount
from app.models.user import User
from app.models.writing_skill import WritingSkill

__all__ = [
    "AuditLog",
    "Campaign",
    "Post",
    "SlackIdentity",
    "SocialAccount",
    "User",
    "WritingSkill",
]
