import pytest

from app.domain.catalog import load_seed
from app.domain.models import Offer as OfferModel
from app.domain.need_rules import offer_to_optimizer, validate_need
from app.optimizer.contract import Offer as OptimizerOffer


def test_validate_need_both_keys() -> None:
    catalog = load_seed()
    with pytest.raises(ValueError, match="exactly one of product_key or family_key"):
        validate_need(
            product_key="fortune_sunlite_oil_5l",
            family_key="sunflower_oil",
            quantity=None,
            qty=1,
            catalog=catalog,
        )


def test_validate_need_neither_key() -> None:
    catalog = load_seed()
    with pytest.raises(ValueError, match="exactly one of product_key or family_key"):
        validate_need(
            product_key=None,
            family_key=None,
            quantity=None,
            qty=1,
            catalog=catalog,
        )


def test_validate_need_exact_with_quantity() -> None:
    catalog = load_seed()
    with pytest.raises(ValueError, match="quantity must be null for exact product needs"):
        validate_need(
            product_key="fortune_sunlite_oil_5l",
            family_key=None,
            quantity="5L",
            qty=1,
            catalog=catalog,
        )


def test_validate_need_flexible_without_quantity() -> None:
    catalog = load_seed()
    with pytest.raises(ValueError, match="quantity is required for flexible family needs"):
        validate_need(
            product_key=None,
            family_key="sunflower_oil",
            quantity=None,
            qty=1,
            catalog=catalog,
        )


def test_validate_need_unknown_product_key() -> None:
    catalog = load_seed()
    with pytest.raises(ValueError, match="Unknown product_key"):
        validate_need(
            product_key="unknown_product_xyz",
            family_key=None,
            quantity=None,
            qty=1,
            catalog=catalog,
        )


def test_validate_need_unknown_family_key() -> None:
    catalog = load_seed()
    with pytest.raises(ValueError, match="Unknown family_key"):
        validate_need(
            product_key=None,
            family_key="unknown_family_xyz",
            quantity="1L",
            qty=1,
            catalog=catalog,
        )


def test_validate_need_unit_mismatch() -> None:
    catalog = load_seed()
    with pytest.raises(ValueError, match="No listings in family 'sunflower_oil' match unit 'g'"):
        validate_need(
            product_key=None,
            family_key="sunflower_oil",
            quantity="5kg",
            qty=1,
            catalog=catalog,
        )


def test_validate_need_quantity_too_large() -> None:
    catalog = load_seed()
    with pytest.raises(ValueError, match="is too large"):
        validate_need(
            product_key=None,
            family_key="sunflower_oil",
            quantity="101L",
            qty=1,
            catalog=catalog,
        )


def test_validate_need_qty_range() -> None:
    catalog = load_seed()
    with pytest.raises(ValueError, match="qty must be 1..99"):
        validate_need(
            product_key="fortune_sunlite_oil_5l",
            family_key=None,
            quantity=None,
            qty=0,
            catalog=catalog,
        )
    with pytest.raises(ValueError, match="qty must be 1..99"):
        validate_need(
            product_key="fortune_sunlite_oil_5l",
            family_key=None,
            quantity=None,
            qty=100,
            catalog=catalog,
        )


def test_validate_need_valid() -> None:
    catalog = load_seed()
    # Exact need
    validate_need(
        product_key="fortune_sunlite_oil_5l",
        family_key=None,
        quantity=None,
        qty=1,
        catalog=catalog,
    )
    # Flexible need
    validate_need(
        product_key=None,
        family_key="sunflower_oil",
        quantity="5L",
        qty=2,
        catalog=catalog,
    )


def test_offer_round_trip() -> None:
    # Test case 8: a stored tiered offer with eligible_categories ["dryfruits"]
    # converts back into an optimizer Offer equal to one built directly.
    record = OfferModel(
        id=10,
        household_id=1,
        code="T1",
        platform="amazon",
        kind="tiered",
        min_order_paise=0,
        value_paise=0,
        rate_bp=0,
        cap_paise=None,
        tiers_json="[[100000, 10000], [200000, 25000]]",
        uses_left=1,
        stack_group="platform_coupon",
        value_type="cash",
        multiplier_bp=None,
        eligible_categories_json='["dryfruits"]',
        valid_to=None,
        note="Test offer",
        archived=False,
    )

    opt_offer = offer_to_optimizer(record)
    expected_offer = OptimizerOffer(
        id="T1",
        platform="amazon",
        kind="tiered",
        min_order=0,
        value=0,
        rate_bp=0,
        cap=None,
        tiers=((100000, 10000), (200000, 25000)),
        uses_left=1,
        stack_group="platform_coupon",
        value_type="cash",
        multiplier_bp=None,
        eligible_categories=frozenset(["dryfruits"]),
    )

    assert opt_offer == expected_offer
