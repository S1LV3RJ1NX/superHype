"""add campaigns.platform

The single platform a campaign runs on (linkedin | x). Existing campaigns are
all LinkedIn, so the column backfills to 'linkedin' via the server default.

Revision ID: e5b2d8f04936
Revises: d4a1c7e93825
Create Date: 2026-06-19 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e5b2d8f04936"
down_revision: str | None = "d4a1c7e93825"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "campaigns",
        sa.Column(
            "platform",
            sa.String(length=32),
            nullable=False,
            server_default="linkedin",
        ),
    )


def downgrade() -> None:
    op.drop_column("campaigns", "platform")
