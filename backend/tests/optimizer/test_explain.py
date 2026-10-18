from app.core.money import format_inr
from app.optimizer.baseline import baseline_plan
from app.optimizer.contract import Offer, Order, OrderLine
from app.optimizer.evaluate import PlanResult, evaluate_plan
from app.optimizer.explain import Reason, explain
from app.optimizer.heuristic import plan_cheapest_now
from app.optimizer.pending import Filler, plan_max_savings
from app.optimizer.planning import Candidate, NeedLine, Plan, PlannedLine
from app.pricing.fee_schedules import Platform


def _need(
    line_id: str,
    price: int,
    platform: Platform,
    cat: str = "staples",
    eta: int = 1440,
    qty: int = 1,
    need_by: int | None = None,
    lock_platform: Platform | None = None,
) -> NeedLine:
    cand = Candidate(
        listing_id=f"{line_id}_{platform}",
        platform=platform,
        unit_price=price,
        eta_minutes=eta,
    )
    return NeedLine(
        line_id=line_id,
        category=cat,
        qty=qty,
        candidates=(cand,),
        need_by_minutes=need_by,
        lock_platform=lock_platform,
    )


def test_split_for_slot_ex_1() -> None:
    # Ex 1: Oil 66500, Surf 34400, Dal 33000 (amazon), A1 uses 2
    oil = _need("oil", 66500, "amazon")
    surf = _need("surf", 34400, "amazon")
    dal = _need("dal", 33000, "amazon")
    a1 = Offer(
        id="A1",
        platform="amazon",
        kind="flat",
        min_order=50000,
        value=5000,
        value_type="amazon_pay",
        uses_left=2,
    )
    memberships = {"amazon": True}
    base = baseline_plan([oil, surf, dal], [a1], memberships)
    plan = plan_cheapest_now([oil, surf, dal], [a1], memberships)

    reasons = explain(plan, base, [a1])
    split_reasons = [r for r in reasons if r.code == "SPLIT_FOR_SLOT"]
    assert len(split_reasons) == 1
    r = split_reasons[0]
    assert r.platform == "amazon"
    assert r.amount == 5000
    assert r.line_ids == ("dal", "oil", "surf")
    assert r.text == "Split Amazon into 2 orders to earn ₹50 more in offers."


def test_dead_weight() -> None:
    # 5. DEAD_WEIGHT: single amazon line 120000, A1 (flat ₹50 >= ₹500) uses 2, line can't be split
    # -> reason amount 5000, text "₹700 above the ₹500 threshold earns nothing. Split it to earn another ₹50."
    item = _need("bulk_item", 120000, "amazon")
    a1 = Offer(
        id="A1",
        platform="amazon",
        kind="flat",
        min_order=50000,
        value=5000,
        uses_left=2,
        value_type="cash",
    )
    memberships = {"amazon": True}
    base = baseline_plan([item], [a1], memberships)
    plan = plan_cheapest_now([item], [a1], memberships)

    reasons = explain(plan, base, [a1])
    dead_weights = [r for r in reasons if r.code == "DEAD_WEIGHT"]
    assert len(dead_weights) == 1
    r = dead_weights[0]
    assert r.platform == "amazon"
    assert r.amount == 5000
    assert r.line_ids == ("bulk_item",)
    assert r.text == "₹700 above the ₹500 threshold earns nothing. Split it to earn another ₹50."


def test_moved_platform_ex_5() -> None:
    # Ex 5: Milk (blinkit 6800), Bread (blinkit 5000), Atta (instamart 28500, blinkit 28900)
    milk = _need("milk", 6800, "blinkit", eta=10, need_by=60)
    bread = _need("bread", 5000, "blinkit", eta=10, need_by=60)
    cand_im = Candidate(listing_id="atta_im", platform="instamart", unit_price=28500, eta_minutes=15)
    cand_bl = Candidate(listing_id="atta_bl", platform="blinkit", unit_price=28900, eta_minutes=10)
    atta = NeedLine(
        line_id="atta",
        category="staples",
        qty=1,
        candidates=(cand_im, cand_bl),
    )
    memberships = {"blinkit": False, "instamart": True}
    base = baseline_plan([milk, bread, atta], [], memberships)
    plan = plan_cheapest_now([milk, bread, atta], [], memberships)

    reasons = explain(plan, base, [])
    moved = [r for r in reasons if r.code == "MOVED_PLATFORM"]
    assert len(moved) == 1
    r = moved[0]
    assert r.platform == "blinkit"
    assert r.amount == 400
    assert r.line_ids == ("atta",)
    assert r.text == "atta moved to Blinkit: ₹4 dearer, but the plan costs less overall."


def test_moved_platform_zero_amount() -> None:
    # Item moves with same unit price (diff == 0)
    cand1 = Candidate(listing_id="c1", platform="amazon", unit_price=30000, eta_minutes=10)
    cand2 = Candidate(listing_id="c2", platform="blinkit", unit_price=30000, eta_minutes=15)
    line1 = NeedLine(line_id="item1", category="staples", qty=1, candidates=(cand1, cand2))
    cand_b = Candidate(listing_id="b", platform="blinkit", unit_price=10000, eta_minutes=15)
    line2 = NeedLine(line_id="item2", category="staples", qty=1, candidates=(cand_b,))

    memberships = {"amazon": True, "blinkit": True}
    base = baseline_plan([line1, line2], [], memberships)
    cand1_bl_only = NeedLine(line_id="item1", category="staples", qty=1, candidates=(cand2,))
    plan = plan_cheapest_now([cand1_bl_only, line2], [], memberships)

    reasons = explain(plan, base, [])
    moved = [r for r in reasons if r.code == "MOVED_PLATFORM"]
    assert len(moved) == 1
    assert moved[0].amount == 0
    assert moved[0].text == "item1 moved to Blinkit to save on fees or unlock an offer."


def test_pending_short_and_filler_suggest_ex_2() -> None:
    # Ex 2
    oil = _need("oil", 66500, "amazon", cat="staples")
    surf = _need("surf", 34400, "amazon", cat="cleaning")
    a1 = Offer(
        id="A1",
        platform="amazon",
        kind="flat",
        min_order=50000,
        value=5000,
        uses_left=2,
        value_type="amazon_pay",
    )
    vim = Filler(
        filler_id="vim",
        listing_id="vim_amazon",
        platform="amazon",
        category="cleaning",
        unit_price=19900,
        score=5,
    )
    memberships = {"amazon": True}
    base = baseline_plan([oil, surf], [a1], memberships)
    sp = plan_max_savings([oil, surf], [a1], memberships, fillers=[vim])

    reasons = explain(sp.plan, base, [a1], pending=sp.pending)
    p_short = [r for r in reasons if r.code == "PENDING_SHORT"]
    assert len(p_short) == 1
    assert p_short[0].platform == "amazon"
    assert p_short[0].amount == 15600
    assert p_short[0].line_ids == ("surf",)
    assert p_short[0].text == "Holding a Amazon basket: ₹156 short of the ₹500 offer threshold."

    f_sug = [r for r in reasons if r.code == "FILLER_SUGGEST"]
    assert len(f_sug) == 1
    assert f_sug[0].platform == "amazon"
    assert f_sug[0].amount == 19900
    assert f_sug[0].line_ids == ("vim",)
    assert f_sug[0].text == f"Add vim ({format_inr(19900)}) to complete it."


def test_uses_exhausted() -> None:
    # 6. USES_EXHAUSTED: A1 uses 1, Ex 1 lines -> plan has 1 order, so no USES_EXHAUSTED.
    # Construct a case with 2 qualifying orders forced by max_orders / lock_platform and 1 use
    # -> exactly one USES_EXHAUSTED reason.
    oil = _need("oil", 66500, "amazon")
    surf = _need("surf", 34400, "amazon")
    dal = _need("dal", 33000, "amazon")
    a1_single = Offer(
        id="A1",
        platform="amazon",
        kind="flat",
        min_order=50000,
        value=5000,
        value_type="amazon_pay",
        uses_left=1,
    )
    memberships = {"amazon": True}
    base = baseline_plan([oil, surf, dal], [a1_single], memberships)
    # With normal cheapest now, 1 order is formed, so no exhausted use on another order
    plan1 = plan_cheapest_now([oil, surf, dal], [a1_single], memberships)
    reasons1 = explain(plan1, base, [a1_single])
    assert not any(r.code == "USES_EXHAUSTED" for r in reasons1)

    # Now force 2 amazon orders by having 2 distinct need items locked or structured
    # e.g. using 2 items of 60000 each with settings max_orders_per_platform=2 or separate orders
    item1 = _need("item1", 60000, "amazon")
    item2 = _need("item2", 60000, "amazon")
    # In order to force 2 orders on amazon, let's create two orders directly or test with a plan
    # where orders = ((line1,), (line2,))
    # evaluate_plan gives order 0 A1 applied, order 1 no offer
    o1_line = PlannedLine("item1", "item1_amazon", "amazon", 60000, 1)
    o2_line = PlannedLine("item2", "item2_amazon", "amazon", 60000, 1)
    eval_o1 = Order("amazon", (OrderLine("item1", "staples", 60000, 1),), is_member=True)
    eval_o2 = Order("amazon", (OrderLine("item2", "staples", 60000, 1),), is_member=True)
    res = evaluate_plan([eval_o1, eval_o2], [a1_single])
    forced_plan = Plan(orders=((o1_line,), (o2_line,)), result=res, unpriced=())
    forced_base = baseline_plan([item1, item2], [a1_single], memberships)

    reasons2 = explain(forced_plan, forced_base, [a1_single])
    exhausted = [r for r in reasons2 if r.code == "USES_EXHAUSTED"]
    assert len(exhausted) == 1
    assert exhausted[0].code == "USES_EXHAUSTED"
    assert exhausted[0].platform == "amazon"
    assert exhausted[0].amount == 0
    assert exhausted[0].line_ids == ("item2",)
    assert exhausted[0].text == "Only 1 use(s) of A1 left, so this order can't get it too."


def test_reasons_sorted_and_amounts_non_negative() -> None:
    # 7. Reasons are sorted, deterministic, and every amount >= 0.
    oil = _need("oil", 66500, "amazon")
    surf = _need("surf", 34400, "amazon")
    a1 = Offer(
        id="A1",
        platform="amazon",
        kind="flat",
        min_order=50000,
        value=5000,
        uses_left=2,
        value_type="amazon_pay",
    )
    vim = Filler(
        filler_id="vim",
        listing_id="vim_amazon",
        platform="amazon",
        category="cleaning",
        unit_price=19900,
        score=5,
    )
    memberships = {"amazon": True}
    base = baseline_plan([oil, surf], [a1], memberships)
    sp = plan_max_savings([oil, surf], [a1], memberships, fillers=[vim])

    reasons = explain(sp.plan, base, [a1], pending=sp.pending)
    for r in reasons:
        assert isinstance(r, Reason)
        assert r.amount >= 0
        assert isinstance(r.line_ids, tuple)
        assert list(r.line_ids) == sorted(r.line_ids)

    # Check order matches ReasonCode definition order:
    code_order = {
        "SPLIT_FOR_SLOT": 0,
        "DEAD_WEIGHT": 1,
        "MOVED_PLATFORM": 2,
        "PENDING_SHORT": 3,
        "FILLER_SUGGEST": 4,
        "USES_EXHAUSTED": 5,
    }
    for i in range(len(reasons) - 1):
        k1 = (code_order[reasons[i].code], reasons[i].platform, reasons[i].line_ids)
        k2 = (code_order[reasons[i + 1].code], reasons[i + 1].platform, reasons[i + 1].line_ids)
        assert k1 <= k2


def test_empty_plan_returns_no_reasons() -> None:
    empty_plan = Plan(
        orders=(),
        result=PlanResult(orders=(), total_subtotal=0, total_fees=0, total_offer_value=0, total_net=0),
        unpriced=(),
    )
    reasons = explain(empty_plan, empty_plan, [])
    assert reasons == ()


def test_no_split_reason_when_a_line_just_moves_onto_a_platform() -> None:
    # Ghee is cheaper on Blinkit (no membership, ₹25 fee) but lands on Amazon with A1. Baseline has
    # 0 Amazon orders and the plan has 1: that's a move, not a split.
    ghee = NeedLine(
        "ghee",
        "dairy",
        1,
        (Candidate("g-a", "amazon", 58900, 1440), Candidate("g-b", "blinkit", 58500, 10)),
    )
    members: dict[Platform, bool] = {
        "amazon": True, "flipkart": True, "blinkit": False, "instamart": True, "zepto": False
    }
    a1 = Offer("A1", "amazon", "flat", min_order=50000, value=5000, uses_left=2)
    plan = plan_cheapest_now([ghee], [a1], members)
    base = baseline_plan([ghee], [a1], members)
    assert [o[0].platform for o in plan.orders] == ["amazon"]
    codes = [r.code for r in explain(plan, base, [a1])]
    assert "SPLIT_FOR_SLOT" not in codes
    assert "MOVED_PLATFORM" in codes
