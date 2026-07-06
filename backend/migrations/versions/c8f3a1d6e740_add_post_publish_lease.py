"""add posts.publish_leased_until (single-flight publish lease)

A worker claims this lease before any provider call, so a recovery job or a
second replica can never run a body-publish or comment concurrently and
double-post. The TTL written into it is the crash backstop.

Revision ID: c8f3a1d6e740
Revises: b6e2f9a4c718
Create Date: 2026-07-06 23:10:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c8f3a1d6e740"
down_revision: str | None = "b6e2f9a4c718"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "posts",
        sa.Column("publish_leased_until", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("posts", "publish_leased_until")
