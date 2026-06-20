"""add posts.first_comment_external_id

Stores the URN of the link-in-first-comment and doubles as the idempotency
marker so a retry resumes at the comment instead of re-publishing the post.

Revision ID: 8a1c4e7d9b20
Revises: 7f3a9c2b1d04
Create Date: 2026-06-20 10:58:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8a1c4e7d9b20"
down_revision: str | None = "7f3a9c2b1d04"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "posts",
        sa.Column("first_comment_external_id", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("posts", "first_comment_external_id")
