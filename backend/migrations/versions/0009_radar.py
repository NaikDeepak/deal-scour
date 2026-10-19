"""radar schema

Revision ID: 0009_radar
Revises: 0008_catalog
Create Date: 2026-10-19 15:15:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0009_radar"
down_revision: str | None = "0008_catalog"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "radar_channel",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("household_id", sa.Integer(), nullable=False),
        sa.Column("peer_id", sqlmodel.sql.sqltypes.AutoString(length=60), nullable=False),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(length=120), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["household_id"], ["household.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("household_id", "peer_id", name="uq_radar_channel_household_peer"),
    )
    op.create_index("ix_radar_channel_household_id", "radar_channel", ["household_id"], unique=False)
    op.create_index("ix_radar_channel_peer_id", "radar_channel", ["peer_id"], unique=False)

    op.create_table(
        "radar_keyword",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("household_id", sa.Integer(), nullable=False),
        sa.Column("keyword", sqlmodel.sql.sqltypes.AutoString(length=80), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["household_id"], ["household.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("household_id", "keyword", name="uq_radar_keyword_household_kw"),
    )
    op.create_index("ix_radar_keyword_household_id", "radar_keyword", ["household_id"], unique=False)

    op.create_table(
        "radar_post",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("household_id", sa.Integer(), nullable=False),
        sa.Column("peer_id", sqlmodel.sql.sqltypes.AutoString(length=60), nullable=False),
        sa.Column("message_id", sqlmodel.sql.sqltypes.AutoString(length=80), nullable=False),
        sa.Column("text", sqlmodel.sql.sqltypes.AutoString(length=2000), nullable=False),
        sa.Column("posted_at", sa.DateTime(), nullable=False),
        sa.Column("verdict", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("reasons_json", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("platform", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("sku", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("listing_id", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("product_url", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("title", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("pack_label", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("family_key", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("posted_paise", sa.Integer(), nullable=True),
        sa.Column("live_paise", sa.Integer(), nullable=True),
        sa.Column("status", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("pairs_json", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("page_fetches", sa.Integer(), nullable=False),
        sa.Column("processed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["household_id"], ["household.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("household_id", "peer_id", "message_id", name="uq_radar_post_household_peer_msg"),
    )
    op.create_index("ix_radar_post_household_id", "radar_post", ["household_id"], unique=False)
    op.create_index("ix_radar_post_peer_id", "radar_post", ["peer_id"], unique=False)
    op.create_index("ix_radar_post_verdict", "radar_post", ["verdict"], unique=False)
    op.create_index("ix_radar_post_status", "radar_post", ["status"], unique=False)
    op.create_index("ix_radar_post_created_at", "radar_post", ["created_at"], unique=False)

    op.create_table(
        "radar_alert",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("household_id", sa.Integer(), nullable=False),
        sa.Column("post_id", sa.Integer(), nullable=True),
        sa.Column("product_key", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("platform", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("sku", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("title", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("url", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("price_paise", sa.Integer(), nullable=False),
        sa.Column("reasons_json", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("telegram_status", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(), nullable=True),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["household_id"], ["household.id"]),
        sa.ForeignKeyConstraint(["post_id"], ["radar_post.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_radar_alert_household_id", "radar_alert", ["household_id"], unique=False)
    op.create_index("ix_radar_alert_product_key", "radar_alert", ["product_key"], unique=False)
    op.create_index("ix_radar_alert_telegram_status", "radar_alert", ["telegram_status"], unique=False)
    op.create_index("ix_radar_alert_scheduled_for", "radar_alert", ["scheduled_for"], unique=False)
    op.create_index("ix_radar_alert_created_at", "radar_alert", ["created_at"], unique=False)

    op.create_table(
        "radar_extension_token",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("household_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("revoked", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["household_id"], ["household.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_radar_extension_token_household_id", "radar_extension_token", ["household_id"], unique=False
    )
    op.create_index(
        "ix_radar_extension_token_token_hash", "radar_extension_token", ["token_hash"], unique=True
    )


def downgrade() -> None:
    op.drop_index("ix_radar_extension_token_token_hash", table_name="radar_extension_token")
    op.drop_index("ix_radar_extension_token_household_id", table_name="radar_extension_token")
    op.drop_table("radar_extension_token")

    op.drop_index("ix_radar_alert_created_at", table_name="radar_alert")
    op.drop_index("ix_radar_alert_scheduled_for", table_name="radar_alert")
    op.drop_index("ix_radar_alert_telegram_status", table_name="radar_alert")
    op.drop_index("ix_radar_alert_product_key", table_name="radar_alert")
    op.drop_index("ix_radar_alert_household_id", table_name="radar_alert")
    op.drop_table("radar_alert")

    op.drop_index("ix_radar_post_created_at", table_name="radar_post")
    op.drop_index("ix_radar_post_status", table_name="radar_post")
    op.drop_index("ix_radar_post_verdict", table_name="radar_post")
    op.drop_index("ix_radar_post_peer_id", table_name="radar_post")
    op.drop_index("ix_radar_post_household_id", table_name="radar_post")
    op.drop_table("radar_post")

    op.drop_index("ix_radar_keyword_household_id", table_name="radar_keyword")
    op.drop_table("radar_keyword")

    op.drop_index("ix_radar_channel_peer_id", table_name="radar_channel")
    op.drop_index("ix_radar_channel_household_id", table_name="radar_channel")
    op.drop_table("radar_channel")
