"""rename team EO/FD to EO/FDE

The founding/engineering team label was corrected from EO/FD to EO/FDE. The prior
migration seeds EO/FD, so on a fresh database this renames that seeded row.

The rename is guarded so it never trips the unique name constraint: if an EO/FDE
row already exists (e.g. seed.py inserted it before this migration ran), the old
EO/FD row is removed instead of renamed into a duplicate.

Revision ID: c4e8a7b013d9
Revises: b2d9f4a1c3e7
Create Date: 2026-07-01 08:30:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c4e8a7b013d9"
down_revision: str | None = "b2d9f4a1c3e7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Rename only when the target name is free; otherwise drop the stale row so we
    # never violate uq_teams_name. Members FK is ON DELETE SET NULL, so no orphan.
    op.execute("""
        UPDATE teams SET name = 'EO/FDE'
        WHERE name = 'EO/FD'
          AND NOT EXISTS (SELECT 1 FROM teams t2 WHERE t2.name = 'EO/FDE')
        """)
    op.execute("DELETE FROM teams WHERE name = 'EO/FD'")


def downgrade() -> None:
    op.execute("""
        UPDATE teams SET name = 'EO/FD'
        WHERE name = 'EO/FDE'
          AND NOT EXISTS (SELECT 1 FROM teams t2 WHERE t2.name = 'EO/FD')
        """)
