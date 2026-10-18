"""baskets schema with plan_run, basket, basket_line

Revision ID: 0002_baskets
Revises: 0001_initial
Create Date: 2026-10-18 21:15:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002_baskets"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "plan_run",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("household_id", sa.Integer(), nullable=False),
        sa.Column("list_id", sa.Integer(), nullable=True),
        sa.Column("request_json", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("response_json", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("accepted_label", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["household_id"], ["household.id"]),
        sa.ForeignKeyConstraint(["list_id"], ["shopping_list.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "basket",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("household_id", sa.Integer(), nullable=False),
        sa.Column("plan_run_id", sa.Integer(), nullable=False),
        sa.Column("platform", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column(
            "status",
            sqlmodel.sql.sqltypes.AutoString(),
            server_default=sa.text("'ready'"),
            nullable=False,
        ),
        sa.Column("target_offer_code", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("threshold_paise", sa.Integer(), nullable=True),
        sa.Column("shortfall_paise", sa.Integer(), nullable=True),
        sa.Column("planned_net_paise", sa.Integer(), nullable=False),
        sa.Column("offer_value_expected_paise", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "offers_json",
            sqlmodel.sql.sqltypes.AutoString(),
            server_default=sa.text("'[]'"),
            nullable=False,
        ),
        sa.Column("actual_paid_paise", sa.Integer(), nullable=True),
        sa.Column("offer_value_received_paise", sa.Integer(), nullable=True),
        sa.Column("placed_at", sa.DateTime(), nullable=True),
        sa.Column("settled_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["household_id"], ["household.id"]),
        sa.ForeignKeyConstraint(["plan_run_id"], ["plan_run.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "basket_line",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("basket_id", sa.Integer(), nullable=False),
        sa.Column("need_id", sa.Integer(), nullable=True),
        sa.Column("listing_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("line_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("title", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("pack_label", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("packs", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("unit_price_paise", sa.Integer(), nullable=False),
        sa.Column("line_total_paise", sa.Integer(), nullable=False),
        sa.Column("is_filler", sa.Boolean(), server_default=sa.text("0"), nullable=False),
        sa.ForeignKeyConstraint(["basket_id"], ["basket.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["need_id"], ["need.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("basket_line")
    op.drop_table("basket")
    op.drop_table("plan_run")
