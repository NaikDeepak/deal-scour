"""price_observation schema

Revision ID: 0003_price_observation
Revises: 0002_baskets
Create Date: 2026-10-18 21:40:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003_price_observation"
down_revision: str | None = "0002_baskets"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "price_observation",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("household_id", sa.Integer(), nullable=False),
        sa.Column("listing_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("listed_paise", sa.Integer(), nullable=False),
        sa.Column("mrp_paise", sa.Integer(), nullable=False),
        sa.Column("member_price_paise", sa.Integer(), nullable=True),
        sa.Column("in_stock", sa.Boolean(), server_default=sa.text("1"), nullable=False),
        sa.Column("eta_minutes", sa.Integer(), nullable=True),
        sa.Column(
            "source",
            sqlmodel.sql.sqltypes.AutoString(),
            server_default=sa.text("'manual'"),
            nullable=False,
        ),
        sa.Column("note", sqlmodel.sql.sqltypes.AutoString(length=120), nullable=True),
        sa.Column("observed_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["household_id"], ["household.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_price_observation_household_listing_observed",
        "price_observation",
        ["household_id", "listing_id", "observed_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_price_observation_household_listing_observed",
        table_name="price_observation",
    )
    op.drop_table("price_observation")
