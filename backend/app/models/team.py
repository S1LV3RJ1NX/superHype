"""Team: an org group (Founders, GTM, Engineering, ...) a user belongs to.

Teams are the targeting unit for campaigns: selecting a team expands to its
members. Each user belongs to at most one team. Teams are archived (is_active
false) rather than hard-deleted so a member's team_id never points at a gone row.
"""

from sqlalchemy import Boolean, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Team(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "teams"

    name: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
