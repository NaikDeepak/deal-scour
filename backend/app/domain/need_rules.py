import json
from collections.abc import Sequence
from typing import Any, cast

from app.domain.catalog import SeedListing, load_seed
from app.domain.models import Offer as OfferModel
from app.optimizer.contract import Offer as OptimizerOffer
from app.optimizer.contract import OfferKind, ValueType
from app.pricing.fee_schedules import Platform
from app.pricing.units import parse_pack

# Largest flexible quantity per need: 100 kg, 100 L, 1000 pieces.
_MAX_QUANTITY = {"g": 100_000, "ml": 100_000, "pc": 1_000}


def validate_need(
    product_key: str | None,
    family_key: str | None,
    quantity: str | None,
    qty: int,
    catalog: Sequence[SeedListing] | None = None,
    line_id: str | None = None,
) -> None:
    if qty < 1 or qty > 99:
        raise ValueError(f"qty must be 1..99, got {qty}")

    has_pk = product_key is not None
    has_fk = family_key is not None
    if (has_pk and has_fk) or (not has_pk and not has_fk):
        prefix = f"Line {line_id}: " if line_id else ""
        raise ValueError(
            f"{prefix}exactly one of product_key or family_key must be set"
        )

    if catalog is None:
        catalog = load_seed()

    seed_by_product = {item.product_key: item for item in catalog}
    seed_by_family: dict[str, list[SeedListing]] = {}
    for item in catalog:
        seed_by_family.setdefault(item.family_key, []).append(item)

    prefix = f"Line {line_id}: " if line_id else ""

    if has_pk:
        assert product_key is not None
        if quantity is not None:
            raise ValueError(
                f"{prefix}quantity must be null for exact product needs"
            )
        if product_key not in seed_by_product:
            raise ValueError(f"Unknown product_key: {product_key}")
    else:
        assert family_key is not None
        if quantity is None:
            raise ValueError(
                f"{prefix}quantity is required for flexible family needs"
            )
        if family_key not in seed_by_family:
            raise ValueError(f"Unknown family_key: {family_key}")

        parsed_pack = parse_pack(quantity)
        if parsed_pack.qty > _MAX_QUANTITY[parsed_pack.unit]:
            raise ValueError(f"{prefix}quantity {quantity} is too large")

        family_listings = seed_by_family[family_key]
        matching_listings = [
            item for item in family_listings if item.pack.unit == parsed_pack.unit
        ]
        if not matching_listings:
            raise ValueError(
                f"No listings in family '{family_key}' match unit '{parsed_pack.unit}'"
            )


def offer_to_optimizer(record: OfferModel | Any) -> OptimizerOffer:
    """Build an optimizer Offer from an Offer database model record."""
    tiers_raw = (
        json.loads(record.tiers_json)
        if isinstance(record.tiers_json, str) and record.tiers_json
        else []
    )
    tiers_tuple = tuple((int(tier[0]), int(tier[1])) for tier in tiers_raw)
    cats = (
        frozenset(json.loads(record.eligible_categories_json))
        if record.eligible_categories_json is not None
        else None
    )

    return OptimizerOffer(
        id=record.code,
        platform=cast(Platform, record.platform),
        kind=cast(OfferKind, record.kind),
        min_order=record.min_order_paise,
        value=record.value_paise,
        rate_bp=record.rate_bp,
        cap=record.cap_paise,
        tiers=tiers_tuple,
        uses_left=record.uses_left,
        stack_group=record.stack_group,
        value_type=cast(ValueType, record.value_type),
        multiplier_bp=record.multiplier_bp,
        eligible_categories=cats,
    )


offer_from_record = offer_to_optimizer
