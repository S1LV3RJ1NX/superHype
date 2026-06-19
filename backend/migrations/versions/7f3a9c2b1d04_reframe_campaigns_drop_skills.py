"""reframe campaigns around interactions and drop writing skills

Adds the campaign type, seed fields, and generation hints; adds posts.target_post_id
and per-variation image columns; creates the assets table; drops the writing_skills
table and the campaign hero/skill/approval columns.

Revision ID: 7f3a9c2b1d04
Revises: 450c91999d3d
Create Date: 2026-06-19 21:50:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7f3a9c2b1d04"
down_revision: str | None = "450c91999d3d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # assets table for uploaded image bytes.
    op.create_table(
        "assets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("content_type", sa.String(length=128), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name="fk_assets_created_by_users"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_assets"),
    )

    # campaigns: new shape.
    op.add_column(
        "campaigns",
        sa.Column(
            "type",
            sa.String(length=16),
            server_default="amplify",
            nullable=False,
        ),
    )
    op.add_column("campaigns", sa.Column("seed_url", sa.Text(), nullable=True))
    op.add_column("campaigns", sa.Column("seed_urn", sa.Text(), nullable=True))
    op.add_column("campaigns", sa.Column("seed_content", sa.Text(), nullable=True))
    op.add_column("campaigns", sa.Column("tone", sa.Text(), nullable=True))
    op.add_column("campaigns", sa.Column("length", sa.String(length=32), nullable=True))
    op.add_column(
        "campaigns",
        sa.Column(
            "language",
            sa.String(length=16),
            server_default="en",
            nullable=False,
        ),
    )
    op.add_column(
        "campaigns", sa.Column("extra_instructions", sa.Text(), nullable=True)
    )
    op.add_column("campaigns", sa.Column("launched_by", sa.Uuid(), nullable=True))
    op.add_column(
        "campaigns",
        sa.Column("launched_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_campaigns_launched_by_users", "campaigns", "users", ["launched_by"], ["id"]
    )
    op.alter_column("campaigns", "raw_brief", existing_type=sa.Text(), nullable=True)

    # Drop the retired hero / skill / approval columns and their FKs.
    op.drop_constraint(
        "fk_campaigns_writing_skill_id_writing_skills", "campaigns", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_campaigns_hero_account_id_social_accounts", "campaigns", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_campaigns_approved_by_users", "campaigns", type_="foreignkey"
    )
    op.drop_column("campaigns", "writing_skill_id")
    op.drop_column("campaigns", "hero_account_id")
    op.drop_column("campaigns", "approved_by")
    op.drop_column("campaigns", "approved_at")

    # posts: interaction target link and per-variation image.
    op.add_column("posts", sa.Column("target_post_id", sa.Uuid(), nullable=True))
    op.add_column("posts", sa.Column("image_asset_id", sa.Uuid(), nullable=True))
    op.add_column("posts", sa.Column("image_url", sa.Text(), nullable=True))
    op.add_column("posts", sa.Column("image_alt", sa.Text(), nullable=True))
    op.create_foreign_key(
        "fk_posts_target_post_id_posts", "posts", "posts", ["target_post_id"], ["id"]
    )
    op.create_foreign_key(
        "fk_posts_image_asset_id_assets", "posts", "assets", ["image_asset_id"], ["id"]
    )
    op.create_index(
        "ix_posts_target_post_id", "posts", ["target_post_id"], unique=False
    )

    # Drop the writing_skills table (and its indexes).
    op.drop_index("ix_writing_skills_status", table_name="writing_skills")
    op.drop_index("ix_writing_skills_is_archived", table_name="writing_skills")
    op.drop_index("uq_writing_skills_is_default", table_name="writing_skills")
    op.drop_table("writing_skills")


def downgrade() -> None:
    op.create_table(
        "writing_skills",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("instructions", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=True),
        sa.Column("is_default", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("is_archived", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("is_seed", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default="published",
            nullable=False,
        ),
        sa.Column("created_by", sa.Uuid(), nullable=True),
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
            ["created_by"], ["users.id"], name="fk_writing_skills_created_by_users"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_writing_skills"),
    )
    op.create_index(
        "uq_writing_skills_is_default",
        "writing_skills",
        ["is_default"],
        unique=True,
        postgresql_where=sa.text("is_default"),
    )
    op.create_index("ix_writing_skills_is_archived", "writing_skills", ["is_archived"])
    op.create_index("ix_writing_skills_status", "writing_skills", ["status"])

    op.drop_index("ix_posts_target_post_id", table_name="posts")
    op.drop_constraint("fk_posts_image_asset_id_assets", "posts", type_="foreignkey")
    op.drop_constraint("fk_posts_target_post_id_posts", "posts", type_="foreignkey")
    op.drop_column("posts", "image_alt")
    op.drop_column("posts", "image_url")
    op.drop_column("posts", "image_asset_id")
    op.drop_column("posts", "target_post_id")

    op.add_column(
        "campaigns",
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("campaigns", sa.Column("approved_by", sa.Uuid(), nullable=True))
    op.add_column("campaigns", sa.Column("hero_account_id", sa.Uuid(), nullable=True))
    op.add_column("campaigns", sa.Column("writing_skill_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_campaigns_approved_by_users", "campaigns", "users", ["approved_by"], ["id"]
    )
    op.create_foreign_key(
        "fk_campaigns_hero_account_id_social_accounts",
        "campaigns",
        "social_accounts",
        ["hero_account_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_campaigns_writing_skill_id_writing_skills",
        "campaigns",
        "writing_skills",
        ["writing_skill_id"],
        ["id"],
    )
    op.alter_column("campaigns", "raw_brief", existing_type=sa.Text(), nullable=False)
    op.drop_constraint(
        "fk_campaigns_launched_by_users", "campaigns", type_="foreignkey"
    )
    op.drop_column("campaigns", "launched_at")
    op.drop_column("campaigns", "launched_by")
    op.drop_column("campaigns", "extra_instructions")
    op.drop_column("campaigns", "language")
    op.drop_column("campaigns", "length")
    op.drop_column("campaigns", "tone")
    op.drop_column("campaigns", "seed_content")
    op.drop_column("campaigns", "seed_urn")
    op.drop_column("campaigns", "seed_url")
    op.drop_column("campaigns", "type")

    op.drop_table("assets")
