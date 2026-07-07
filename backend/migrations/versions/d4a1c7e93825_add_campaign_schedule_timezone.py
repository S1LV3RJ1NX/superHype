"""add campaigns.schedule_timezone

The IANA timezone the creator entered scheduled_at in. Used only to interpret
the wall-clock input at save time; storage stays UTC and firing is a pure UTC
comparison. Null means the company default (settings.SCHEDULE_TIMEZONE).

Revision ID: d4a1c7e93825
Revises: c8f3a1d6e740
Create Date: 2026-07-07 13:50:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d4a1c7e93825"
down_revision: str | None = "c8f3a1d6e740"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "campaigns",
        sa.Column("schedule_timezone", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("campaigns", "schedule_timezone")
