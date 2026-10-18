"""initial schema with household, shopping_list, need, offer

Revision ID: 0001_initial
Revises:
Create Date: 2026-10-18 21:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "household",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("pincode", sqlmodel.sql.sqltypes.AutoString(length=6), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "shopping_list",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("household_id", sa.Integer(), nullable=False),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(length=60), nullable=False),
        sa.Column("kind", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("archived", sa.Boolean(), server_default=sa.text("0"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["household_id"], ["household.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "need",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("list_id", sa.Integer(), nullable=False),
        sa.Column("line_id", sqlmodel.sql.sqltypes.AutoString(length=80), nullable=False),
        sa.Column("product_key", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("family_key", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("quantity", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("qty", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("need_by_minutes", sa.Integer(), nullable=True),
        sa.Column("lock_platform", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column(
            "status",
            sqlmodel.sql.sqltypes.AutoString(),
            server_default=sa.text("'open'"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["list_id"], ["shopping_list.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("list_id", "line_id", name="uq_need_list_line"),
    )

    op.create_table(
        "offer",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("household_id", sa.Integer(), nullable=False),
        sa.Column("code", sqlmodel.sql.sqltypes.AutoString(length=20), nullable=False),
        sa.Column("platform", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("kind", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("min_order_paise", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("value_paise", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("rate_bp", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("cap_paise", sa.Integer(), nullable=True),
        sa.Column(
            "tiers_json",
            sqlmodel.sql.sqltypes.AutoString(),
            server_default=sa.text("'[]'"),
            nullable=False,
        ),
        sa.Column("uses_left", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "stack_group",
            sqlmodel.sql.sqltypes.AutoString(),
            server_default=sa.text("'platform_coupon'"),
            nullable=False,
        ),
        sa.Column(
            "value_type",
            sqlmodel.sql.sqltypes.AutoString(),
            server_default=sa.text("'cash'"),
            nullable=False,
        ),
        sa.Column("multiplier_bp", sa.Integer(), nullable=True),
        sa.Column("eligible_categories_json", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column("note", sqlmodel.sql.sqltypes.AutoString(length=200), nullable=True),
        sa.Column("archived", sa.Boolean(), server_default=sa.text("0"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["household_id"], ["household.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_offer_household_code_active",
        "offer",
        ["household_id", "code"],
        unique=True,
        sqlite_where=sa.text("archived = 0"),
    )

    household_table = sa.table(
        "household",
        sa.column("id", sa.Integer),
        sa.column("name", sa.String),
        sa.column("pincode", sa.String),
    )
    op.bulk_insert(
        household_table,
        [{"id": 1, "name": "Home", "pincode": "411018"}],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_offer_household_code_active",
        table_name="offer",
        sqlite_where=sa.text("archived = 0"),
    )
    op.drop_table("offer")
    op.drop_table("need")
    op.drop_table("shopping_list")
    op.drop_table("household")
