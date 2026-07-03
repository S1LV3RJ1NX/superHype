"""add posts (campaign_id, user_id) composite index

Backs the participant-scoped campaign post listing, where a plain participant
sees only their own posts filtered on campaign_id + user_id.

Revision ID: e7a4c9d2f150
Revises: d5f1a2b3c4e6
Create Date: 2026-07-03 13:45:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e7a4c9d2f150"
down_revision: str | None = "d5f1a2b3c4e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("ix_posts_campaign_id_user_id", "posts", ["campaign_id", "user_id"])


def downgrade() -> None:
    op.drop_index("ix_posts_campaign_id_user_id", table_name="posts")
