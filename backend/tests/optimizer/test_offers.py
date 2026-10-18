import pytest

from app.optimizer.contract import Offer, Order, OrderLine
from app.optimizer.offers import effective_value, eligible_subtotal, face_value


def test_case_1_flat_offer() -> None:
    # 1. Flat ₹50 >= ₹500: face_value at 49999 -> 0, at 50000 -> 5000
    offer = Offer(
        id="A1",
        platform="amazon",
        kind="flat",
        min_order=50000,
        value=5000,
    )
    assert face_value(offer, 49999) == 0
    assert face_value(offer, 50000) == 5000


def test_case_2_pct_cap_offer() -> None:
    # 2. pct_cap 10% cap ₹100 min ₹500: at 49999 -> 0. At 80000 -> 8000.
    # At 100000 -> 10000. At 180000 -> 10000 (capped). With cap=None at 180000 -> 18000.
    offer = Offer(
        id="P1",
        platform="amazon",
        kind="pct_cap",
        min_order=50000,
        rate_bp=1000,
        cap=10000,
    )
    assert face_value(offer, 49999) == 0
    assert face_value(offer, 80000) == 8000
    assert face_value(offer, 100000) == 10000
    assert face_value(offer, 180000) == 10000

    uncapped_offer = Offer(
        id="P2",
        platform="amazon",
        kind="pct_cap",
        min_order=50000,
        rate_bp=1000,
        cap=None,
    )
    assert face_value(uncapped_offer, 180000) == 18000


def test_case_3_tiered_offer() -> None:
    # 3. Tiered ((99900, 7500), (149900, 15000)): 99899 -> 0, 99900 -> 7500, 149899 -> 7500, 152000 -> 15000.
    offer = Offer(
        id="T1",
        platform="flipkart",
        kind="tiered",
        tiers=((99900, 7500), (149900, 15000)),
    )
    assert face_value(offer, 99899) == 0
    assert face_value(offer, 99900) == 7500
    assert face_value(offer, 149899) == 7500
    assert face_value(offer, 152000) == 15000


def test_case_4_effective_value() -> None:
    # 4. effective_value: supercoins face 10000 -> 8000. Explicit multiplier_bp=5000 -> 5000.
    # Cash -> 10000. Floor: supercoins face 999 -> 799.
    supercoin_offer = Offer(
        id="S1",
        platform="flipkart",
        kind="flat",
        value=10000,
        value_type="supercoins",
    )
    assert effective_value(supercoin_offer, 10000) == 8000
    assert effective_value(supercoin_offer, 999) == 799

    explicit_offer = Offer(
        id="E1",
        platform="amazon",
        kind="flat",
        value=10000,
        multiplier_bp=5000,
    )
    assert effective_value(explicit_offer, 10000) == 5000

    cash_offer = Offer(
        id="C1",
        platform="amazon",
        kind="flat",
        value=10000,
        value_type="cash",
    )
    assert effective_value(cash_offer, 10000) == 10000


def test_case_5_eligible_subtotal() -> None:
    # 5. eligible_subtotal with eligible_categories={"dryfruits"}
    # on lines (dryfruits 61900, electronics 29900) -> 61900. With None -> 91800.
    order = Order(
        platform="amazon",
        lines=(
            OrderLine(line_id="l1", category="dryfruits", unit_price=61900),
            OrderLine(line_id="l2", category="electronics", unit_price=29900),
        ),
        is_member=True,
    )

    restricted_offer = Offer(
        id="D1",
        platform="amazon",
        kind="flat",
        value=5000,
        eligible_categories=frozenset({"dryfruits"}),
    )
    assert eligible_subtotal(restricted_offer, order) == 61900

    unrestricted_offer = Offer(
        id="D2",
        platform="amazon",
        kind="flat",
        value=5000,
        eligible_categories=None,
    )
    assert eligible_subtotal(unrestricted_offer, order) == 91800


def test_case_6_validation() -> None:
    # 6. Validation: flat with value 0, pct_cap with rate_bp 0 or 10001,
    # tiered with tiers ((99900, 7500), (99900, 9000)), uses_left -1,
    # and an empty Order all raise ValueError. OrderLine qty 0 raises ValueError.
    with pytest.raises(ValueError):
        Offer(id="F0", platform="amazon", kind="flat", value=0)

    with pytest.raises(ValueError):
        Offer(id="P0", platform="amazon", kind="pct_cap", rate_bp=0)

    with pytest.raises(ValueError):
        Offer(id="P10001", platform="amazon", kind="pct_cap", rate_bp=10001)

    with pytest.raises(ValueError):
        Offer(
            id="T_bad",
            platform="flipkart",
            kind="tiered",
            tiers=((99900, 7500), (99900, 9000)),
        )

    with pytest.raises(ValueError):
        Offer(id="U_bad", platform="amazon", kind="flat", value=5000, uses_left=-1)

    with pytest.raises(ValueError):
        Order(platform="amazon", lines=(), is_member=True)

    with pytest.raises(ValueError):
        OrderLine(line_id="l0", category="staples", unit_price=1000, qty=0)


def test_case_22_order_line_negative_unit_price() -> None:
    # 22. OrderLine with unit_price < 0 -> ValueError
    with pytest.raises(ValueError):
        OrderLine(line_id="l1", category="staples", unit_price=-100)


def test_case_23_offer_unknown_kind() -> None:
    # 23. Offer with kind not in flat/pct_cap/tiered (e.g. "bogus") -> ValueError
    with pytest.raises(ValueError):
        Offer(id="O_bogus", platform="amazon", kind="bogus")  # type: ignore[arg-type]
