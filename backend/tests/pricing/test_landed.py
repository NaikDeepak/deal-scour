from dataclasses import FrozenInstanceError

import pytest

from app.pricing.landed import ItemPrice, discount_bp, line_price, unit_price


def test_unit_price_member_and_non_member() -> None:
    # ItemPrice(listed=29200, mrp=36500, member_price=27700): member -> 27700, non-member -> 29200
    p = ItemPrice(listed=29200, mrp=36500, member_price=27700)
    assert unit_price(p, is_member=True) == 27700
    assert unit_price(p, is_member=False) == 29200


def test_unit_price_member_fallback_to_listed() -> None:
    # member_price=None, member -> falls back to listed
    p = ItemPrice(listed=29200, mrp=36500, member_price=None)
    assert unit_price(p, is_member=True) == 29200
    assert unit_price(p, is_member=False) == 29200


def test_unit_price_coupon_and_flooring() -> None:
    # item_coupon=2500 on listed 36900, non-member -> 34400
    p = ItemPrice(listed=36900, mrp=45000, item_coupon=2500)
    assert unit_price(p, is_member=False) == 34400

    # Coupon larger than price -> 0, never negative
    p_high_coupon = ItemPrice(listed=1000, mrp=2000, item_coupon=2500)
    assert unit_price(p_high_coupon, is_member=False) == 0


def test_line_price() -> None:
    p = ItemPrice(listed=29200, mrp=36500)
    assert line_price(p, 3, False) == 3 * unit_price(p, False)

    with pytest.raises(ValueError):
        line_price(p, 0, False)
    with pytest.raises(ValueError):
        line_price(p, -1, False)
    with pytest.raises(TypeError):
        line_price(p, 2.5, False)  # type: ignore[arg-type]


def test_regression_d15_discount_bp() -> None:
    # Regression D15: discount_bp(ItemPrice(listed=29200, mrp=36500), False) == 2000 (20.00%)
    # No delivery fee is involved
    p = ItemPrice(listed=29200, mrp=36500)
    assert discount_bp(p, is_member=False) == 2000
    assert discount_bp(p, is_member=True) == 2000


def test_discount_bp_edge_cases() -> None:
    # discount_bp with mrp 0 -> 0; listed above mrp -> 0, never negative
    p_zero_mrp = ItemPrice(listed=1000, mrp=0)
    assert discount_bp(p_zero_mrp, is_member=False) == 0

    p_neg_mrp = ItemPrice(listed=1000, mrp=-500)
    assert discount_bp(p_neg_mrp, is_member=False) == 0

    p_above_mrp = ItemPrice(listed=40000, mrp=36500)
    assert discount_bp(p_above_mrp, is_member=False) == 0


def test_item_price_frozen_and_types() -> None:
    p = ItemPrice(listed=29200, mrp=36500)
    with pytest.raises(FrozenInstanceError):
        p.listed = 30000  # type: ignore[misc]

    with pytest.raises(TypeError):
        ItemPrice(listed=292.5, mrp=36500)  # type: ignore[arg-type]
