"""catalog categories vocabulary remap

Revision ID: 0010_catalog_categories
Revises: 0009_radar
Create Date: 2026-10-19 18:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0010_catalog_categories"
down_revision: str | None = "0009_radar"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_REMAP_GROUPS: list[tuple[str, list[str]]] = [
    (
        "dryfruits",
        [
            "dry_fruits_nuts",
            "dry_fruits",
            "almonds",
            "cashews",
            "raisins",
            "walnuts",
            "pistachios",
            "dates",
            "dry fruits & nuts",
            "dry fruits and nuts",
        ],
    ),
    (
        "staples",
        [
            "dal_pulses",
            "rice_grains_flours",
            "spices_masalas",
            "spices",
            "masalas",
            "cooking_essentials",
            "packaged_ready_mixes",
            "dal & pulses",
            "dal and pulses",
            "rice, grains & flours",
            "rice, grains and flours",
            "spices & masalas",
            "spices and masalas",
            "cooking essentials",
            "packaged ready mixes",
        ],
    ),
    (
        "breakfast",
        [
            "breakfast_cereals",
            "breakfast & cereals",
            "breakfast and cereals",
        ],
    ),
    (
        "snacks",
        [
            "snacks_savoury",
            "snacks_savory",
            "snacks & savoury",
            "snacks and savoury",
            "snacks & savory",
            "snacks and savory",
        ],
    ),
]


def upgrade() -> None:
    for target_cat, old_cats in _REMAP_GROUPS:
        old_quoted = ", ".join(f"'{c}'" for c in old_cats)
        for table in ("catalog_product", "custom_listing"):
            op.execute(
                sa.text(
                    f"UPDATE {table} SET category = '{target_cat}' WHERE lower(category) IN ({old_quoted})"
                )
            )


def downgrade() -> None:
    # Reversible as a no-op downgrade (ADR-006 / spec)
    pass
