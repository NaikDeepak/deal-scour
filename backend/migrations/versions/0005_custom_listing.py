"""custom_listing schema

Revision ID: 0005_custom_listing
Revises: 0004_auth
Create Date: 2026-10-18 23:25:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005_custom_listing"
down_revision: str | None = "0004_auth"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "custom_listing",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("household_id", sa.Integer(), nullable=False),
        sa.Column("listing_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("platform", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("sku", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("url", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("title", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("brand", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("pack_label", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("category", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("product_key", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("family_key", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("icon", sqlmodel.sql.sqltypes.AutoString(), server_default=sa.text("'🛒'"), nullable=False),
        sa.Column("archived", sa.Boolean(), server_default=sa.text("0"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["household_id"], ["household.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_custom_listing_listing_id", "custom_listing", ["listing_id"], unique=True)
    op.create_index("ix_custom_listing_product_key", "custom_listing", ["product_key"], unique=False)
    op.create_index("ix_custom_listing_family_key", "custom_listing", ["family_key"], unique=False)
    op.create_index(
        "ix_custom_listing_household_platform_sku_active",
        "custom_listing",
        ["household_id", "platform", "sku"],
        unique=True,
        sqlite_where=sa.text("archived = 0"),
    )


def downgrade() -> None:
    op.drop_index("ix_custom_listing_household_platform_sku_active", table_name="custom_listing")
    op.drop_index("ix_custom_listing_family_key", table_name="custom_listing")
    op.drop_index("ix_custom_listing_product_key", table_name="custom_listing")
    op.drop_index("ix_custom_listing_listing_id", table_name="custom_listing")
    op.drop_table("custom_listing")
