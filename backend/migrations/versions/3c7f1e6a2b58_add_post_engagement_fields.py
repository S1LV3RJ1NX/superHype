"""add posts.engagement_url and posts.acknowledged_at

Backs assisted-manual engagement: until Community Management API access lands,
a comment or like becomes a guided human action. engagement_url is the deep
link to the target post the owner opens to act by hand, and acknowledged_at
records when they marked it done.

Revision ID: 3c7f1e6a2b58
Revises: 8a1c4e7d9b20
Create Date: 2026-06-30 18:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3c7f1e6a2b58"
down_revision: str | None = "8a1c4e7d9b20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("posts", sa.Column("engagement_url", sa.Text(), nullable=True))
    op.add_column(
        "posts",
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("posts", "acknowledged_at")
    op.drop_column("posts", "engagement_url")
