"""add users.auto_approve_consented_at (opt-in auto-approve consent)

Null means the person approves every action themselves. A timestamp records
when they opted in to having their actions approved automatically after a
review window; it is only honored while MANUAL_APPROVAL_ONLY is off.

Revision ID: b3d7f1a9c4e2
Revises: a9c2e5f7d310
Create Date: 2026-11-25 12:45:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b3d7f1a9c4e2"
down_revision: str | None = "a9c2e5f7d310"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("auto_approve_consented_at", sa.DateTime(timezone=True)),
    )


def downgrade() -> None:
    op.drop_column("users", "auto_approve_consented_at")
