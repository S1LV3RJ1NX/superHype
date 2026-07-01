"""add teams table and users.team_id

Teams are the org groups a user belongs to (one per user) and the targeting unit
for campaigns. users.team_id is nullable: null means the user has not finished
onboarding and must pick a team. The default teams are seeded here so onboarding
has options in every environment right after upgrade.

Revision ID: b2d9f4a1c3e7
Revises: 3c7f1e6a2b58
Create Date: 2026-07-01 01:50:00.000000

"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b2d9f4a1c3e7"
down_revision: str | None = "3c7f1e6a2b58"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Fixed ids so the seed is stable and idempotent across environments.
_DEFAULT_TEAMS = [
    ("0f9b1a52-0001-4a00-8000-000000000001", "Founders"),
    ("0f9b1a52-0001-4a00-8000-000000000002", "Founder's Office"),
    ("0f9b1a52-0001-4a00-8000-000000000003", "GTM"),
    ("0f9b1a52-0001-4a00-8000-000000000004", "Marketing and Sales"),
    ("0f9b1a52-0001-4a00-8000-000000000005", "Engineering"),
    ("0f9b1a52-0001-4a00-8000-000000000006", "EO/FD"),
]


def upgrade() -> None:
    op.create_table(
        "teams",
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_teams")),
        sa.UniqueConstraint("name", name=op.f("uq_teams_name")),
    )

    op.add_column("users", sa.Column("team_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_users_team_id_teams"),
        "users",
        "teams",
        ["team_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(op.f("ix_users_team_id"), "users", ["team_id"], unique=False)

    teams_table = sa.table(
        "teams",
        sa.column("id", sa.Uuid()),
        sa.column("name", sa.Text()),
    )
    op.bulk_insert(
        teams_table,
        [{"id": uuid.UUID(tid), "name": name} for tid, name in _DEFAULT_TEAMS],
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_users_team_id"), table_name="users")
    op.drop_constraint(op.f("fk_users_team_id_teams"), "users", type_="foreignkey")
    op.drop_column("users", "team_id")
    op.drop_table("teams")
