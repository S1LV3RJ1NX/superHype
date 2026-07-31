"""add posts.source (ai vs manual provenance)

Drafts can now be imported from a spreadsheet instead of generated, and a
hand-edited body stops being "AI generated". The source column records which,
drives the AI/Manual badge in the UI, and lets regenerate rewrite AI text
while leaving manual drafts alone.

Revision ID: a9c2e5f7d310
Revises: e5b2d8f04936
Create Date: 2026-07-31 12:05:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a9c2e5f7d310"
down_revision: str | None = "e5b2d8f04936"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "posts",
        sa.Column("source", sa.String(16), nullable=False, server_default="ai"),
    )


def downgrade() -> None:
    op.drop_column("posts", "source")
