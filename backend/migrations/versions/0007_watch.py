"""watch and llm_usage schema

Revision ID: 0007_watch
Revises: 0006_source_status
Create Date: 2026-10-19 12:45:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007_watch"
down_revision: str | None = "0006_source_status"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "listing_watch",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("household_id", sa.Integer(), nullable=False),
        sa.Column("listing_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("target_paise", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["household_id"], ["household.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("household_id", "listing_id", name="uq_listing_watch_household_listing"),
    )
    op.create_index("ix_listing_watch_household_id", "listing_watch", ["household_id"], unique=False)
    op.create_index("ix_listing_watch_listing_id", "listing_watch", ["listing_id"], unique=False)

    op.create_table(
        "llm_usage",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("household_id", sa.Integer(), nullable=True),
        sa.Column("provider", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("model", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("response_tokens", sa.Integer(), nullable=False),
        sa.Column("total_tokens", sa.Integer(), nullable=False),
        sa.Column("cost_paise", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["household_id"], ["household.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_llm_usage_household_id", "llm_usage", ["household_id"], unique=False)
    op.create_index("ix_llm_usage_created_at", "llm_usage", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_llm_usage_created_at", table_name="llm_usage")
    op.drop_index("ix_llm_usage_household_id", table_name="llm_usage")
    op.drop_table("llm_usage")
    op.drop_index("ix_listing_watch_listing_id", table_name="listing_watch")
    op.drop_index("ix_listing_watch_household_id", table_name="listing_watch")
    op.drop_table("listing_watch")
