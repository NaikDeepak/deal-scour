from dataclasses import FrozenInstanceError

import pytest

from app.pricing.fee_schedules import (
    SAMPLE_SCHEDULES,
    FeeSchedule,
    order_fees,
)


def test_amazon_member() -> None:
    # Amazon, Prime member, subtotal ₹100 -> delivery 0, total 0
    amazon = SAMPLE_SCHEDULES["amazon"]
    assert isinstance(amazon, FeeSchedule)
    breakdown = order_fees(amazon, subtotal=10000, is_member=True)
    assert breakdown.delivery == 0
    assert breakdown.total == 0


def test_amazon_non_member() -> None:
    # Amazon, non-member: subtotal ₹498 (49800) -> delivery 4000. Subtotal ₹499 (49900) -> delivery 0.
    amazon = SAMPLE_SCHEDULES["amazon"]
    bd1 = order_fees(amazon, subtotal=49800, is_member=False)
    assert bd1.delivery == 4000
    assert bd1.total == 4000

    bd2 = order_fees(amazon, subtotal=49900, is_member=False)
    assert bd2.delivery == 0
    assert bd2.total == 0


def test_instamart_member_and_non_member() -> None:
    # Instamart, member: 19899 -> delivery 2500. 19900 -> 0. Non-member at 19900 -> 2500 (threshold is 49900).
    im = SAMPLE_SCHEDULES["instamart"]
    bd_mem_under = order_fees(im, subtotal=19899, is_member=True)
    assert bd_mem_under.delivery == 2500

    bd_mem_at = order_fees(im, subtotal=19900, is_member=True)
    assert bd_mem_at.delivery == 0

    bd_non_mem = order_fees(im, subtotal=19900, is_member=False)
    assert bd_non_mem.delivery == 2500


def test_blinkit_small_cart() -> None:
    # Blinkit, non-member: subtotal 9800 -> delivery 2500 + small_cart 1500 = total 4000.
    # Subtotal 9900 -> small_cart 0.
    blinkit = SAMPLE_SCHEDULES["blinkit"]
    bd_small = order_fees(blinkit, subtotal=9800, is_member=False)
    assert bd_small.delivery == 2500
    assert bd_small.small_cart == 1500
    assert bd_small.total == 4000

    bd_no_small = order_fees(blinkit, subtotal=9900, is_member=False)
    assert bd_no_small.small_cart == 0
    assert bd_no_small.delivery == 2500
    assert bd_no_small.total == 2500


def test_regression_d4_one_fee_per_order() -> None:
    # Regression D4 (one fee per order): five Instamart non-member items of ₹50 each -> one order,
    # subtotal 25000 -> total fees 2500 (not 5 x 2500)
    im = SAMPLE_SCHEDULES["instamart"]
    bd = order_fees(im, subtotal=25000, is_member=False)
    assert bd.delivery == 2500
    assert bd.total == 2500


def test_zero_subtotal_no_order() -> None:
    # order_fees(..., subtotal=0, ...) -> total 0 even for a non-member on Blinkit
    blinkit = SAMPLE_SCHEDULES["blinkit"]
    bd = order_fees(blinkit, subtotal=0, is_member=False)
    assert bd.delivery == 0
    assert bd.small_cart == 0
    assert bd.surge == 0
    assert bd.total == 0


def test_surge_and_validation() -> None:
    # Surge is added: Blinkit member, 30000, surge 2000 -> total 2000
    blinkit = SAMPLE_SCHEDULES["blinkit"]
    bd = order_fees(blinkit, subtotal=30000, is_member=True, surge=2000)
    assert bd.delivery == 0
    assert bd.surge == 2000
    assert bd.total == 2000

    with pytest.raises(ValueError):
        order_fees(blinkit, subtotal=-100, is_member=True)

    with pytest.raises(ValueError):
        order_fees(blinkit, subtotal=10000, is_member=True, surge=-50)

    with pytest.raises(TypeError):
        order_fees(blinkit, subtotal=100.5, is_member=True)  # type: ignore[arg-type]


def test_sample_schedules_exact_values() -> None:
    assert set(SAMPLE_SCHEDULES.keys()) == {"amazon", "flipkart", "blinkit", "instamart", "zepto"}

    amz = SAMPLE_SCHEDULES["amazon"]
    assert amz.delivery_fee == 4000
    assert amz.free_delivery_min == 49900
    assert amz.member_free_delivery_min == 0

    fk = SAMPLE_SCHEDULES["flipkart"]
    assert fk.delivery_fee == 4000
    assert fk.free_delivery_min == 49900
    assert fk.member_free_delivery_min == 0

    im = SAMPLE_SCHEDULES["instamart"]
    assert im.delivery_fee == 2500
    assert im.free_delivery_min == 49900
    assert im.member_free_delivery_min == 19900
    assert im.small_cart_below == 9900
    assert im.small_cart_fee == 1500

    bl = SAMPLE_SCHEDULES["blinkit"]
    assert bl.delivery_fee == 2500
    assert bl.free_delivery_min == 19900
    assert bl.member_free_delivery_min == 0
    assert bl.small_cart_below == 9900
    assert bl.small_cart_fee == 1500

    zp = SAMPLE_SCHEDULES["zepto"]
    assert zp.delivery_fee == 2500
    assert zp.free_delivery_min == 19900
    assert zp.member_free_delivery_min == 0
    assert zp.small_cart_below == 9900
    assert zp.small_cart_fee == 1500


def test_fee_schedule_frozen() -> None:
    amz = SAMPLE_SCHEDULES["amazon"]
    with pytest.raises(FrozenInstanceError):
        amz.delivery_fee = 0  # type: ignore[misc]
