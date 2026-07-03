"""add content_rules table and campaign rules fields

Global content rules (a singleton document) applied to every campaign's
generation, plus per-campaign custom_rules and an apply_global_rules toggle.

Revision ID: f1b8c3d5e290
Revises: e7a4c9d2f150
Create Date: 2026-07-03 14:10:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f1b8c3d5e290"
down_revision: str | None = "e7a4c9d2f150"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "content_rules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["users.id"],
            name=op.f("fk_content_rules_updated_by_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_content_rules")),
    )
    op.add_column("campaigns", sa.Column("custom_rules", sa.Text(), nullable=True))
    op.add_column(
        "campaigns",
        sa.Column(
            "apply_global_rules",
            sa.Boolean(),
            nullable=False,
            server_default="true",
        ),
    )


def downgrade() -> None:
    op.drop_column("campaigns", "apply_global_rules")
    op.drop_column("campaigns", "custom_rules")
    op.drop_table("content_rules")
