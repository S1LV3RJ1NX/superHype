"""add campaign_media table (multiple media per distribute campaign)

An ordered pool of media (images, GIFs, videos) per campaign. At plan build one
item is assigned to each poster by even rotation. Existing campaigns that carry
a single image_asset_id are backfilled as a one-item pool so behavior is
preserved.

Revision ID: a3d7e9c1f482
Revises: f1b8c3d5e290
Create Date: 2026-07-04 13:45:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a3d7e9c1f482"
down_revision: str | None = "f1b8c3d5e290"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "campaign_media",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("campaign_id", sa.Uuid(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("alt", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["campaign_id"],
            ["campaigns.id"],
            name=op.f("fk_campaign_media_campaign_id_campaigns"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["asset_id"],
            ["assets.id"],
            name=op.f("fk_campaign_media_asset_id_assets"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_campaign_media")),
    )
    op.create_index("ix_campaign_media_campaign_id", "campaign_media", ["campaign_id"])
    # Backfill: campaigns with a single uploaded asset become a one-item pool.
    op.execute("""
        INSERT INTO campaign_media (id, campaign_id, asset_id, position, alt, created_at)
        SELECT gen_random_uuid(), id, image_asset_id, 0, image_alt, now()
        FROM campaigns
        WHERE image_asset_id IS NOT NULL
        """)


def downgrade() -> None:
    op.drop_index("ix_campaign_media_campaign_id", table_name="campaign_media")
    op.drop_table("campaign_media")
