from app.core.money import format_inr
from app.optimizer.contract import Offer
from app.optimizer.pending import Filler
from app.optimizer.planning import Candidate, NeedLine
from app.optimizer.planset import PlanSet, plan
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


def test_ex_1_golden() -> None:
    # 1. Ex 1 (A1 uses 2): plan() -> labels ("cheapest_now",) only. Cheapest now savings_vs_baseline == 5000.
    # Reasons include exactly one SPLIT_FOR_SLOT, amazon, amount 5000,
    # text "Split Amazon into 2 orders to earn ₹50 more in offers."
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
    pset = plan(
        needs=[oil, surf, dal],
        offers=[a1],
        memberships={"amazon": True},
    )
    assert isinstance(pset, PlanSet)

    labels = tuple(p.label for p in pset.plans)
    assert labels == ("cheapest_now",)

    cn = pset.plans[0]
    assert cn.savings_vs_baseline == 5000
    assert cn.effective_cost == 123900

    split_reasons = [r for r in cn.reasons if r.code == "SPLIT_FOR_SLOT"]
    assert len(split_reasons) == 1
    assert split_reasons[0].platform == "amazon"
    assert split_reasons[0].amount == 5000
    assert split_reasons[0].text == "Split Amazon into 2 orders to earn ₹50 more in offers."


def test_ex_2_golden() -> None:
    # 2. Ex 2: labels ("cheapest_now", "max_savings").
    # max_savings effective_cost == 90900, savings_vs_baseline == 5000 (baseline 95900).
    # Reasons: PENDING_SHORT text "Holding a Amazon basket: ₹156 short of the ₹500 offer threshold."
    # and FILLER_SUGGEST text "Add vim (₹199) to complete it." with filler_id "vim".
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

    pset = plan(
        needs=[oil, surf],
        offers=[a1],
        memberships={"amazon": True},
        fillers=[vim],
    )

    labels = tuple(p.label for p in pset.plans)
    assert labels == ("cheapest_now", "max_savings")

    ms = pset.plans[1]
    assert ms.effective_cost == 90900
    assert ms.savings_vs_baseline == 5000
    assert pset.baseline.result.total_net == 95900

    short_reasons = [r for r in ms.reasons if r.code == "PENDING_SHORT"]
    assert len(short_reasons) == 1
    assert short_reasons[0].text == "Holding a Amazon basket: ₹156 short of the ₹500 offer threshold."

    filler_reasons = [r for r in ms.reasons if r.code == "FILLER_SUGGEST"]
    assert len(filler_reasons) == 1
    assert filler_reasons[0].text == f"Add vim ({format_inr(19900)}) to complete it."


def test_ex_5_golden() -> None:
    # 3. Ex 5: labels include cheapest_now. Atta has a MOVED_PLATFORM reason to blinkit,
    # amount 400, text "atta moved to Blinkit: ₹4 dearer, but the plan costs less overall."
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

    pset = plan(
        needs=[milk, bread, atta],
        offers=[],
        memberships=memberships,
    )

    labels = tuple(p.label for p in pset.plans)
    assert "cheapest_now" in labels

    cn = pset.plans[0]
    moved = [r for r in cn.reasons if r.code == "MOVED_PLATFORM"]
    assert len(moved) == 1
    assert moved[0].amount == 400
    assert moved[0].text == "atta moved to Blinkit: ₹4 dearer, but the plan costs less overall."


def test_fastest_picks_minimum_eta_and_negative_savings() -> None:
    # 4. Fastest: lines with candidates at eta 10 (₹300) and eta 1440 (₹250)
    # -> fastest picks eta-10 candidates and has negative savings_vs_baseline.
    # With all candidates at the same eta -> no fastest label.
    cand_fast = Candidate("item_bl", "blinkit", unit_price=30000, eta_minutes=10)
    cand_slow = Candidate("item_amz", "amazon", unit_price=25000, eta_minutes=1440)
    item = NeedLine("item", "staples", qty=1, candidates=(cand_fast, cand_slow))

    pset = plan(
        needs=[item],
        offers=[],
        memberships={"blinkit": True, "amazon": True},
    )

    labels = tuple(p.label for p in pset.plans)
    assert "fastest" in labels
    fastest_plan = next(p for p in pset.plans if p.label == "fastest")
    assert fastest_plan.savings_vs_baseline < 0
    assert fastest_plan.plan.orders[0][0].platform == "blinkit"

    # Now with all candidates at same eta:
    cand1 = Candidate("c1", "blinkit", unit_price=30000, eta_minutes=10)
    cand2 = Candidate("c2", "amazon", unit_price=25000, eta_minutes=10)
    item_same_eta = NeedLine("item", "staples", qty=1, candidates=(cand1, cand2))
    pset_same = plan(
        needs=[item_same_eta],
        offers=[],
        memberships={"blinkit": True, "amazon": True},
    )
    labels_same = tuple(p.label for p in pset_same.plans)
    assert "fastest" not in labels_same


def test_empty_needs() -> None:
    # 8. plan() on an empty needs list -> baseline with no orders,
    # plans == (cheapest_now with no orders,), no reasons.
    pset = plan(
        needs=[],
        offers=[],
        memberships={},
    )
    assert len(pset.baseline.orders) == 0
    assert len(pset.plans) == 1
    assert pset.plans[0].label == "cheapest_now"
    assert len(pset.plans[0].plan.orders) == 0
    assert len(pset.plans[0].reasons) == 0


def test_dead_weight_in_planset() -> None:
    # A single ₹1,200 item can't be split into two ₹500+ orders, so plan() gives no DEAD_WEIGHT hint
    # (it appears only when a real split exists, e.g. max_orders_per_platform=1; see test_explain).
    item = _need("item", 120000, "amazon")
    a1 = Offer(
        id="A1",
        platform="amazon",
        kind="flat",
        min_order=50000,
        value=5000,
        uses_left=2,
        value_type="cash",
    )
    pset = plan(
        needs=[item],
        offers=[a1],
        memberships={"amazon": True},
    )
    cn = pset.plans[0]
    assert not [r for r in cn.reasons if r.code == "DEAD_WEIGHT"]

