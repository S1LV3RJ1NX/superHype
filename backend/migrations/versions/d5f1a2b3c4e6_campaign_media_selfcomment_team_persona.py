"""add campaigns.image_asset_id, campaigns.self_comment, teams.persona

Campaign-level media (an uploaded image or short video applied to every post)
is referenced by image_asset_id. self_comment holds the author's own follow-up
comment ("link in the comments"), copied to each post and placed after a delay.
teams.persona is admin-editable voice guidance injected into generated
comments and reshares so interactions read in the member's team tone.

Revision ID: d5f1a2b3c4e6
Revises: c4e8a7b013d9
Create Date: 2026-07-01 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d5f1a2b3c4e6"
down_revision: str | None = "c4e8a7b013d9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("campaigns", sa.Column("image_asset_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_campaigns_image_asset_id_assets"),
        "campaigns",
        "assets",
        ["image_asset_id"],
        ["id"],
    )
    op.add_column("campaigns", sa.Column("self_comment", sa.Text(), nullable=True))
    op.add_column("teams", sa.Column("persona", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("teams", "persona")
    op.drop_column("campaigns", "self_comment")
    op.drop_constraint(
        op.f("fk_campaigns_image_asset_id_assets"), "campaigns", type_="foreignkey"
    )
    op.drop_column("campaigns", "image_asset_id")
