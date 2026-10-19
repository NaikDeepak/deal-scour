"""catalog_product schema

Revision ID: 0008_catalog
Revises: 0007_watch
Create Date: 2026-10-19 14:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0008_catalog"
down_revision: str | None = "0007_watch"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "catalog_product",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("household_id", sa.Integer(), nullable=False),
        sa.Column("seed_product_id", sqlmodel.sql.sqltypes.AutoString(length=40), nullable=False),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(length=160), nullable=False),
        sa.Column("brand", sqlmodel.sql.sqltypes.AutoString(length=80), nullable=False),
        sa.Column("category", sqlmodel.sql.sqltypes.AutoString(length=80), nullable=False),
        sa.Column("family_key", sqlmodel.sql.sqltypes.AutoString(length=40), nullable=False),
        sa.Column("pack_label", sqlmodel.sql.sqltypes.AutoString(length=20), nullable=False),
        sa.Column("target_pack_weight_g", sa.Integer(), nullable=False),
        sa.Column("suggestions_json", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["household_id"], ["household.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("household_id", "seed_product_id", name="uq_catalog_product_household_seed_id"),
    )
    op.create_index("ix_catalog_product_household_id", "catalog_product", ["household_id"], unique=False)
    op.create_index(
        "ix_catalog_product_seed_product_id", "catalog_product", ["seed_product_id"], unique=False
    )
    op.create_index("ix_catalog_product_family_key", "catalog_product", ["family_key"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_catalog_product_family_key", table_name="catalog_product")
    op.drop_index("ix_catalog_product_seed_product_id", table_name="catalog_product")
    op.drop_index("ix_catalog_product_household_id", table_name="catalog_product")
    op.drop_table("catalog_product")
