"""SQLAlchemy models. Importing this package registers every table on Base.metadata."""

from app.models.asset import Asset
from app.models.audit_log import AuditLog
from app.models.campaign import Campaign
from app.models.content_rule import ContentRule
from app.models.post import Post
from app.models.slack_identity import SlackIdentity
from app.models.social_account import SocialAccount
from app.models.team import Team
from app.models.user import User

__all__ = [
    "Asset",
    "AuditLog",
    "Campaign",
    "ContentRule",
    "Post",
    "SlackIdentity",
    "SocialAccount",
    "Team",
    "User",
]
