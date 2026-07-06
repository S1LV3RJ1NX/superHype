"""add campaigns.scheduled_at (scheduled auto-launch + events calendar)

Optional scheduled launch time. When set, the campaign blocks its whole calendar
day (company timezone) for everyone else and a worker poll auto-launches it once
the time arrives. Indexed so the due-campaign poll and the events-calendar range
query are cheap.

Revision ID: b6e2f9a4c718
Revises: a3d7e9c1f482
Create Date: 2026-07-06 21:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b6e2f9a4c718"
down_revision: str | None = "a3d7e9c1f482"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "campaigns",
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_campaigns_scheduled_at", "campaigns", ["scheduled_at"])


def downgrade() -> None:
    op.drop_index("ix_campaigns_scheduled_at", table_name="campaigns")
    op.drop_column("campaigns", "scheduled_at")
