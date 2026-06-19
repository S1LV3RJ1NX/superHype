"""Metadata-level tests for SQLAlchemy models: table registration and indexes."""

import app.models  # noqa: F401
from app.db.base import Base

EXPECTED_TABLES = {
    "users",
    "social_accounts",
    "assets",
    "campaigns",
    "posts",
    "audit_log",
    "slack_identities",
}


def test_all_tables_registered():
    assert set(Base.metadata.tables) >= EXPECTED_TABLES


def test_writing_skills_table_removed():
    assert "writing_skills" not in Base.metadata.tables


def test_post_keyset_and_unique_constraints():
    posts = Base.metadata.tables["posts"]
    index_names = {idx.name for idx in posts.indexes}
    assert {"ix_posts_campaign_id_status", "ix_posts_user_id_status"} <= index_names
    unique_cols = {
        col.name for col in posts.columns if col.unique or col.name == "idempotency_key"
    }
    assert "idempotency_key" in unique_cols


def test_post_has_target_and_image_columns():
    posts = Base.metadata.tables["posts"]
    assert "target_post_id" in posts.columns
    assert "image_asset_id" in posts.columns


def test_campaign_reshaped_columns():
    campaigns = Base.metadata.tables["campaigns"]
    assert "type" in campaigns.columns
    assert "seed_urn" in campaigns.columns
    assert "writing_skill_id" not in campaigns.columns
    assert "hero_account_id" not in campaigns.columns
