"""Metadata-level tests for SQLAlchemy models: table registration and indexes."""

import app.models  # noqa: F401
from app.db.base import Base

EXPECTED_TABLES = {
    "users",
    "social_accounts",
    "writing_skills",
    "campaigns",
    "posts",
    "audit_log",
    "slack_identities",
}


def test_all_tables_registered():
    assert set(Base.metadata.tables) >= EXPECTED_TABLES


def test_partial_unique_default_skill_index():
    indexes = Base.metadata.tables["writing_skills"].indexes
    by_name = {idx.name: idx for idx in indexes}
    partial = by_name["uq_writing_skills_is_default"]
    assert partial.unique is True
    assert partial.dialect_kwargs.get("postgresql_where") is not None


def test_post_keyset_and_unique_constraints():
    posts = Base.metadata.tables["posts"]
    index_names = {idx.name for idx in posts.indexes}
    assert {"ix_posts_campaign_id_status", "ix_posts_user_id_status"} <= index_names
    unique_cols = {
        col.name for col in posts.columns if col.unique or col.name == "idempotency_key"
    }
    assert "idempotency_key" in unique_cols
