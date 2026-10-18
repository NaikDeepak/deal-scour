import time

from app.optimizer.evaluate import evaluate_plan

from app.optimizer.contract import Offer, Order, OrderLine


def _make_line(category: str, price: int, line_id: str = "l") -> OrderLine:
    return OrderLine(line_id=line_id, category=category, unit_price=price, qty=1)


def test_case_7_and_8_and_9_ex_1_and_6() -> None:
    # Offer A1 = flat ₹50 >= ₹500, amazon, value_type="amazon_pay"
    # Lines: Oil 66500, Surf 34400, Dal 33000 (category "staples")
    line_oil = _make_line("staples", 66500, "oil")
    line_surf = _make_line("staples", 34400, "surf")
    line_dal = _make_line("staples", 33000, "dal")

    # 7. Ex 1, A1 uses_left=2, one order (Oil, Surf, Dal) -> total_net == 128900, one applied offer
    offer_a1_u2 = Offer(
        id="A1",
        platform="amazon",
        kind="flat",
        min_order=50000,
        value=5000,
        value_type="amazon_pay",
        uses_left=2,
    )
    order_single = Order(platform="amazon", lines=(line_oil, line_surf, line_dal), is_member=True)
    res_7 = evaluate_plan([order_single], [offer_a1_u2])
    assert res_7.total_net == 128900
    assert len(res_7.orders[0].applied) == 1

    # 8. Ex 1, A1 uses_left=2, orders (Oil) + (Surf, Dal) -> total_net == 123900, total_offer_value == 10000
    order_1 = Order(platform="amazon", lines=(line_oil,), is_member=True)
    order_2 = Order(platform="amazon", lines=(line_surf, line_dal), is_member=True)
    res_8 = evaluate_plan([order_1, order_2], [offer_a1_u2])
    assert res_8.total_net == 123900
    assert res_8.total_offer_value == 10000

    # 9. Ex 6, A1 uses_left=1, orders (Oil) + (Surf, Dal) -> total_net == 128900.
    # Exactly one order has the offer: order 0, by the tie-break.
    offer_a1_u1 = Offer(
        id="A1",
        platform="amazon",
        kind="flat",
        min_order=50000,
        value=5000,
        value_type="amazon_pay",
        uses_left=1,
    )
    res_9 = evaluate_plan([order_1, order_2], [offer_a1_u1])
    assert res_9.total_net == 128900
    assert len(res_9.orders[0].applied) == 1
    assert len(res_9.orders[1].applied) == 0


def test_case_10_ex_3_pct_cap() -> None:
    # 10. Ex 3, flipkart B1 = pct_cap 1000 bp, cap 10000, min 50000, stack_group="bank", uses_left=2
    b1 = Offer(
        id="B1",
        platform="flipkart",
        kind="pct_cap",
        rate_bp=1000,
        cap=10000,
        min_order=50000,
        stack_group="bank",
        uses_left=2,
    )
    # one order of a single 180000 line -> total_net == 170000
    ord_single = Order(
        platform="flipkart",
        lines=(_make_line("electronics", 180000),),
        is_member=True,
    )
    res_single = evaluate_plan([ord_single], [b1])
    assert res_single.total_net == 170000

    # Orders 100000 + 80000 -> total_net == 162000
    ord_1 = Order(
        platform="flipkart",
        lines=(_make_line("electronics", 100000),),
        is_member=True,
    )
    ord_2 = Order(
        platform="flipkart",
        lines=(_make_line("electronics", 80000),),
        is_member=True,
    )
    res_split = evaluate_plan([ord_1, ord_2], [b1])
    assert res_split.total_net == 162000


def test_case_11_ex_4_tiered() -> None:
    # 11. Ex 4, flipkart C1 tiered ((99900, 7500), (149900, 15000)), uses_left=1
    c1 = Offer(
        id="C1",
        platform="flipkart",
        kind="tiered",
        tiers=((99900, 7500), (149900, 15000)),
        uses_left=1,
    )
    # one order 152000 -> 137000
    ord_single = Order(platform="flipkart", lines=(_make_line("appliances", 152000),), is_member=True)
    res_single = evaluate_plan([ord_single], [c1])
    assert res_single.total_net == 137000

    # Orders 99900 + 52100 -> 144500
    ord_1 = Order(platform="flipkart", lines=(_make_line("appliances", 99900),), is_member=True)
    ord_2 = Order(platform="flipkart", lines=(_make_line("appliances", 52100),), is_member=True)
    res_split = evaluate_plan([ord_1, ord_2], [c1])
    assert res_split.total_net == 144500


def test_case_12_ex_7_category_restriction() -> None:
    # 12. Ex 7, amazon D1 flat ₹50 >= ₹500 eligible_categories={"dryfruits"}
    d1 = Offer(
        id="D1",
        platform="amazon",
        kind="flat",
        min_order=50000,
        value=5000,
        eligible_categories=frozenset({"dryfruits"}),
    )
    # order (dryfruits 61900, electronics 29900) -> 86800
    ord_qual = Order(
        platform="amazon",
        lines=(
            _make_line("dryfruits", 61900),
            _make_line("electronics", 29900),
        ),
        is_member=True,
    )
    assert evaluate_plan([ord_qual], [d1]).total_net == 86800

    # order (dryfruits 40000, electronics 29900) -> no offer, 69900
    ord_not_qual = Order(
        platform="amazon",
        lines=(
            _make_line("dryfruits", 40000),
            _make_line("electronics", 29900),
        ),
        is_member=True,
    )
    assert evaluate_plan([ord_not_qual], [d1]).total_net == 69900


def test_case_13_ex_5_fees_blinkit() -> None:
    # 13. Ex 5 fees, blinkit non-member: order (6800, 5000) -> fees.delivery 2500, net == 14300.
    # Order (6800, 5000, 28900) -> delivery 0, net == 40700.
    ord_small = Order(
        platform="blinkit",
        lines=(_make_line("groceries", 6800), _make_line("groceries", 5000)),
        is_member=False,
    )
    res_small = evaluate_plan([ord_small], [])
    assert res_small.orders[0].fees.delivery == 2500
    assert res_small.orders[0].net == 14300

    ord_large = Order(
        platform="blinkit",
        lines=(
            _make_line("groceries", 6800),
            _make_line("groceries", 5000),
            _make_line("groceries", 28900),
        ),
        is_member=False,
    )
    res_large = evaluate_plan([ord_large], [])
    assert res_large.orders[0].fees.delivery == 0
    assert res_large.orders[0].net == 40700


def test_case_14_greedy_trap() -> None:
    # 14. Greedy trap. amazon X = flat 5000 >= 30000 (uses 1), Y = flat 4000 >= 50000 (uses 1), same group.
    # Orders A = 60000, B = 40000 -> A gets Y, B gets X, total_offer_value == 9000.
    # A greedy best-per-order pass would give 5000.
    x = Offer(id="X", platform="amazon", kind="flat", min_order=30000, value=5000, uses_left=1)
    y = Offer(id="Y", platform="amazon", kind="flat", min_order=50000, value=4000, uses_left=1)
    order_a = Order(platform="amazon", lines=(_make_line("staples", 60000),), is_member=True)
    order_b = Order(platform="amazon", lines=(_make_line("staples", 40000),), is_member=True)

    res = evaluate_plan([order_a, order_b], [x, y])
    assert res.total_offer_value == 9000
    assert res.orders[0].applied[0].offer_id == "Y"
    assert res.orders[1].applied[0].offer_id == "X"


def test_case_15_stacking() -> None:
    # 15. Stacking: amazon P = flat 5000 >= 50000 (group "platform_coupon"),
    # K = pct_cap 1000 bp cap 10000 min 50000 (group "bank").
    # One order of 100000 -> both apply, net == 85000, applied sorted by id.
    p = Offer(
        id="P", platform="amazon", kind="flat", min_order=50000, value=5000, stack_group="platform_coupon"
    )
    k = Offer(
        id="K",
        platform="amazon",
        kind="pct_cap",
        min_order=50000,
        rate_bp=1000,
        cap=10000,
        stack_group="bank",
    )
    order = Order(platform="amazon", lines=(_make_line("staples", 100000),), is_member=True)

    res = evaluate_plan([order], [p, k])
    assert res.total_net == 85000
    applied_ids = [a.offer_id for a in res.orders[0].applied]
    assert applied_ids == ["K", "P"]


def test_case_16_same_group_exclusive() -> None:
    # 16. Same group, two offers, one order of 100000: P1 flat 5000 >= 50000 and P2 flat 7500 >= 50000
    # -> only P2 applies, net == 92500.
    p1 = Offer(id="P1", platform="amazon", kind="flat", min_order=50000, value=5000)
    p2 = Offer(id="P2", platform="amazon", kind="flat", min_order=50000, value=7500)
    order = Order(platform="amazon", lines=(_make_line("staples", 100000),), is_member=True)

    res = evaluate_plan([order], [p1, p2])
    assert res.total_net == 92500
    assert len(res.orders[0].applied) == 1
    assert res.orders[0].applied[0].offer_id == "P2"


def test_case_17_equal_value_tie() -> None:
    # 17. Equal-value tie: Q1 and Q2 both flat 5000 >= 50000, same group, uses 1, one order
    # -> applied offer id is "Q1".
    q1 = Offer(id="Q1", platform="amazon", kind="flat", min_order=50000, value=5000)
    q2 = Offer(id="Q2", platform="amazon", kind="flat", min_order=50000, value=5000)
    order = Order(platform="amazon", lines=(_make_line("staples", 100000),), is_member=True)

    res = evaluate_plan([order], [q1, q2])
    assert len(res.orders[0].applied) == 1
    assert res.orders[0].applied[0].offer_id == "Q1"


def test_case_18_platform_mismatch_and_zero_uses() -> None:
    # 18. Platform mismatch: a flipkart offer is never applied to an amazon order.
    # uses_left=0 -> never applied.
    fk_offer = Offer(id="FK1", platform="flipkart", kind="flat", min_order=50000, value=5000)
    amz_zero_uses = Offer(id="A0", platform="amazon", kind="flat", min_order=50000, value=5000, uses_left=0)
    order = Order(platform="amazon", lines=(_make_line("staples", 100000),), is_member=True)

    res = evaluate_plan([order], [fk_offer, amz_zero_uses])
    assert len(res.orders[0].applied) == 0


def test_case_19_fewer_uses_tie_break() -> None:
    # 19. Fewer-uses tie-break: R = flat 5000 >= 50000, uses 2, multiplier_bp=0 (worth nothing).
    # Two qualifying orders -> no applied offers at all.
    r = Offer(
        id="R", platform="amazon", kind="flat", min_order=50000, value=5000, uses_left=2, multiplier_bp=0
    )
    order_1 = Order(platform="amazon", lines=(_make_line("staples", 60000),), is_member=True)
    order_2 = Order(platform="amazon", lines=(_make_line("staples", 60000),), is_member=True)

    res = evaluate_plan([order_1, order_2], [r])
    assert res.total_offer_value == 0
    assert len(res.orders[0].applied) == 0
    assert len(res.orders[1].applied) == 0


def test_case_20_totals_and_consistency() -> None:
    # 20. Totals: for any plan, total_net == total_subtotal + total_fees - total_offer_value,
    # and each OrderResult.net follows its formula. Check on the plan from case 15
    # plus a blinkit non-member order.
    p = Offer(
        id="P", platform="amazon", kind="flat", min_order=50000, value=5000, stack_group="platform_coupon"
    )
    k = Offer(
        id="K",
        platform="amazon",
        kind="pct_cap",
        min_order=50000,
        rate_bp=1000,
        cap=10000,
        stack_group="bank",
    )
    amz_order = Order(platform="amazon", lines=(_make_line("staples", 100000),), is_member=True)
    blinkit_order = Order(
        platform="blinkit",
        lines=(_make_line("groceries", 6800), _make_line("groceries", 5000)),
        is_member=False,
    )

    res = evaluate_plan([amz_order, blinkit_order], [p, k])
    for o in res.orders:
        assert o.net == o.subtotal + o.fees.total - sum(a.effective_value for a in o.applied)
    assert res.total_net == res.total_subtotal + res.total_fees - res.total_offer_value


def test_case_21_performance() -> None:
    # 21. Performance: 8 amazon orders of 50000..120000 and 5 flat offers (uses 1-3)
    # in one group evaluate in < 50 ms (use time.perf_counter, allow 3 attempts).
    orders = [
        Order(platform="amazon", lines=(_make_line("staples", 50000 + i * 10000),), is_member=True)
        for i in range(8)
    ]
    offers = [
        Offer(
            id=f"O{i}",
            platform="amazon",
            kind="flat",
            min_order=40000 + i * 10000,
            value=1000 * (i + 1),
            uses_left=(i % 3) + 1,
            stack_group="group1",
        )
        for i in range(5)
    ]

    passed = False
    for _ in range(3):
        t0 = time.perf_counter()
        evaluate_plan(orders, offers)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        if elapsed_ms < 50.0:
            passed = True
            break

    assert passed, f"Performance test failed: elapsed {elapsed_ms:.2f} ms >= 50 ms"
