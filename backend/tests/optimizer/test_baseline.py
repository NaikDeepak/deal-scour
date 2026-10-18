from app.optimizer.baseline import allowed_candidates, baseline_plan
from app.optimizer.contract import Offer
from app.optimizer.planning import Candidate, NeedLine


def _need(
    line_id: str,
    price: int,
    platform: str,
    cat: str = "staples",
    eta: int = 1440,
    qty: int = 1,
    need_by: int | None = None,
    lock_platform: str | None = None,
) -> NeedLine:
    cand = Candidate(
        listing_id=f"{line_id}_{platform}",
        platform=platform,  # type: ignore[arg-type]
        unit_price=price,
        eta_minutes=eta,
    )
    return NeedLine(
        line_id=line_id,
        category=cat,
        qty=qty,
        candidates=(cand,),
        need_by_minutes=need_by,
        lock_platform=lock_platform,  # type: ignore[arg-type]
    )


def test_allowed_candidates_filtering_and_sorting() -> None:
    # 1. need_by 60 drops a 1440-min candidate. lock_platform keeps only that platform.
    # Sort by price, then eta, then listing_id.
    c_slow = Candidate(listing_id="c_slow", platform="amazon", unit_price=10000, eta_minutes=1440)
    c_fast = Candidate(listing_id="c_fast", platform="amazon", unit_price=10000, eta_minutes=30)
    c_cheaper_fast = Candidate(
        listing_id="c_cheaper_fast", platform="amazon", unit_price=9000, eta_minutes=45
    )
    c_other_platform = Candidate(
        listing_id="c_other", platform="flipkart", unit_price=8000, eta_minutes=20
    )

    line = NeedLine(
        line_id="item1",
        category="staples",
        qty=1,
        candidates=(c_slow, c_fast, c_cheaper_fast, c_other_platform),
        need_by_minutes=60,
        lock_platform="amazon",
    )

    allowed = allowed_candidates(line)
    # c_slow dropped (eta 1440 > 60)
    # c_other_platform dropped (platform flipkart != amazon)
    # Remaining: c_cheaper_fast (unit_price 9000), c_fast (unit_price 10000)
    assert len(allowed) == 2
    assert allowed[0] == c_cheaper_fast
    assert allowed[1] == c_fast

    # Tie-break test on same price and eta, sorted by listing_id
    c1 = Candidate(listing_id="cand_b", platform="amazon", unit_price=5000, eta_minutes=60)
    c2 = Candidate(listing_id="cand_a", platform="amazon", unit_price=5000, eta_minutes=60)
    line2 = NeedLine(
        line_id="item2",
        category="staples",
        qty=1,
        candidates=(c1, c2),
    )
    allowed2 = allowed_candidates(line2)
    assert allowed2 == (c2, c1)


def test_unpriced_lines_go_to_unpriced() -> None:
    # 2. A line with no allowed candidate goes to unpriced and is not in any order.
    c_slow = Candidate(listing_id="c_slow", platform="amazon", unit_price=10000, eta_minutes=1440)
    line_unpriced = NeedLine(
        line_id="urgent_item",
        category="staples",
        qty=1,
        candidates=(c_slow,),
        need_by_minutes=30,  # drops c_slow
    )
    line_priced = _need("item_ok", 5000, "amazon")

    plan = baseline_plan(
        needs=[line_unpriced, line_priced],
        offers=[],
        memberships={"amazon": True},
    )

    assert plan.unpriced == ("urgent_item",)
    assert len(plan.orders) == 1
    assert len(plan.orders[0]) == 1
    assert plan.orders[0][0].line_id == "item_ok"


def test_baseline_puts_all_amazon_lines_in_one_order() -> None:
    # 3. Baseline puts all Amazon lines in one order:
    # Ex 1 lines with A1 (flat ₹50 >= ₹500, uses 2) -> total_net == 128900
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

    plan = baseline_plan(
        needs=[oil, surf, dal],
        offers=[a1],
        memberships={"amazon": True},
    )

    assert len(plan.orders) == 1
    # Check that lines inside the order are sorted by line_id: "dal", "oil", "surf"
    line_ids_in_order = tuple(pline.line_id for pline in plan.orders[0])
    assert line_ids_in_order == ("dal", "oil", "surf")
    assert plan.result.total_net == 128900
    assert plan.unpriced == ()
