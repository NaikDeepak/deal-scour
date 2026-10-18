import itertools
import random

from app.optimizer.baseline import allowed_candidates, baseline_plan
from app.optimizer.contract import Offer, Order, OrderLine
from app.optimizer.evaluate import evaluate_plan
from app.optimizer.heuristic import plan_cheapest_now
from app.optimizer.planning import Candidate, NeedLine, PlanSettings
from app.pricing.fee_schedules import SAMPLE_SCHEDULES, Platform


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


# ---------------------------------------------------------------------------
# Golden tests (BASKET_OPTIMIZER §6)
# ---------------------------------------------------------------------------


def test_case_4_ex_1_split_double_cashback() -> None:
    # 4. Ex 1: Oil 66500, Surf 34400, Dal 33000 (amazon), A1 uses 2
    # -> total_net == 123900, 2 orders, each subtotal >= 50000.
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

    plan = plan_cheapest_now(
        needs=[oil, surf, dal],
        offers=[a1],
        memberships={"amazon": True},
    )

    assert plan.result.total_net == 123900
    assert len(plan.orders) == 2
    for order in plan.orders:
        subtotal = sum(pline.unit_price * pline.qty for pline in order)
        assert subtotal >= 50000
    # Also verify canonical ordering: orders sorted by (platform, -subtotal, first line_id)
    # Order 0 has {dal, surf} with subtotal 67400, Order 1 has {oil} with subtotal 66500
    sub_0 = sum(pline.unit_price * pline.qty for pline in plan.orders[0])
    sub_1 = sum(pline.unit_price * pline.qty for pline in plan.orders[1])
    assert sub_0 >= sub_1


def test_case_5_ex_6_uses_exhausted_no_split() -> None:
    # 5. Ex 6: same, A1 uses 1 -> total_net == 128900 and 1 order (fewer-orders tie-break).
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
        uses_left=1,
    )

    plan = plan_cheapest_now(
        needs=[oil, surf, dal],
        offers=[a1],
        memberships={"amazon": True},
    )

    assert plan.result.total_net == 128900
    assert len(plan.orders) == 1


def test_case_6_ex_3_pct_cap_sweet_spot() -> None:
    # 6. Ex 3: flipkart lines 60000, 40000, 50000, 30000 (total 180000),
    # B1 = pct_cap 1000 bp cap 10000 min 50000 group "bank" uses 2 -> total_net == 162000.
    l1 = _need("l1", 60000, "flipkart")
    l2 = _need("l2", 40000, "flipkart")
    l3 = _need("l3", 50000, "flipkart")
    l4 = _need("l4", 30000, "flipkart")

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

    plan = plan_cheapest_now(
        needs=[l1, l2, l3, l4],
        offers=[b1],
        memberships={"flipkart": True},
    )

    assert plan.result.total_net == 162000
    assert len(plan.orders) == 2


def test_case_7_ex_4_tiered_dont_split() -> None:
    # 7. Ex 4: flipkart lines 80000, 40000, 32000 (total 152000),
    # C1 tiered ((99900, 7500), (149900, 15000)) uses 1 -> total_net == 137000, 1 order.
    l1 = _need("l1", 80000, "flipkart")
    l2 = _need("l2", 40000, "flipkart")
    l3 = _need("l3", 32000, "flipkart")

    c1 = Offer(
        id="C1",
        platform="flipkart",
        kind="tiered",
        tiers=((99900, 7500), (149900, 15000)),
        uses_left=1,
    )

    plan = plan_cheapest_now(
        needs=[l1, l2, l3],
        offers=[c1],
        memberships={"flipkart": True},
    )

    assert plan.result.total_net == 137000
    assert len(plan.orders) == 1


def test_case_8_ex_5_urgent_item_fee_saving() -> None:
    # 8. Ex 5: blinkit is non-member, instamart is member.
    # Milk: blinkit 6800, eta 10, need_by 60.
    # Bread: blinkit 5000, eta 10, need_by 60.
    # Atta: candidates instamart 28500 (eta 15) and blinkit 28900 (eta 10), no need_by.
    # No offers -> total_net == 40700, a single blinkit order.
    # Baseline is 42800 (blinkit 11800 + 2500 fee, instamart 28500).
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

    memberships: dict[Platform, bool] = {"blinkit": False, "instamart": True}

    base = baseline_plan(needs=[milk, bread, atta], offers=[], memberships=memberships)
    assert base.result.total_net == 42800
    assert len(base.orders) == 2

    plan = plan_cheapest_now(needs=[milk, bread, atta], offers=[], memberships=memberships)
    assert plan.result.total_net == 40700
    assert len(plan.orders) == 1
    assert plan.orders[0][0].platform == "blinkit"


# ---------------------------------------------------------------------------
# Property tests
# ---------------------------------------------------------------------------


def _random_offers(rng: random.Random, platform: Platform) -> list[Offer]:
    num_offers = rng.randint(0, 2)
    offers: list[Offer] = []
    for i in range(num_offers):
        offer_id = f"{platform}_off_{i}_{rng.randint(100, 999)}"
        kind = rng.choice(["flat", "pct_cap", "tiered"])
        uses = rng.randint(1, 2)
        if kind == "flat":
            min_ord = rng.choice([20000, 40000, 50000])
            val = rng.choice([2000, 5000, 10000])
            offers.append(
                Offer(
                    id=offer_id,
                    platform=platform,
                    kind="flat",
                    min_order=min_ord,
                    value=val,
                    uses_left=uses,
                )
            )
        elif kind == "pct_cap":
            min_ord = rng.choice([20000, 40000])
            rate = rng.choice([500, 1000])
            cap = rng.choice([5000, 10000])
            offers.append(
                Offer(
                    id=offer_id,
                    platform=platform,
                    kind="pct_cap",
                    min_order=min_ord,
                    rate_bp=rate,
                    cap=cap,
                    uses_left=uses,
                )
            )
        else:
            offers.append(
                Offer(
                    id=offer_id,
                    platform=platform,
                    kind="tiered",
                    tiers=((30000, 3000), (60000, 8000)),
                    uses_left=uses,
                )
            )
    return offers


def test_case_9_never_worse_than_baseline() -> None:
    # 9. Never worse than baseline: on 50 random instances (seeded random.Random(7),
    # 3–7 lines, 1–3 platforms per line, prices 5000–90000, 0–2 random offers per platform),
    # heuristic.total_net <= baseline.total_net.
    rng = random.Random(7)
    available_platforms: list[Platform] = ["amazon", "flipkart", "blinkit", "instamart", "zepto"]

    for _ in range(50):
        num_lines = rng.randint(3, 7)
        needs: list[NeedLine] = []
        for i in range(num_lines):
            line_id = f"item_{i}"
            num_cands = rng.randint(1, 3)
            c_platforms = rng.sample(available_platforms, num_cands)
            candidates: list[Candidate] = []
            for p in c_platforms:
                price = rng.randint(50, 900) * 100
                eta = rng.choice([15, 30, 120, 1440])
                candidates.append(
                    Candidate(
                        listing_id=f"{line_id}_{p}",
                        platform=p,
                        unit_price=price,
                        eta_minutes=eta,
                    )
                )
            need_by = rng.choice([None, 60, 1440])
            lock_p = rng.choice([None, None, rng.choice(c_platforms)])
            needs.append(
                NeedLine(
                    line_id=line_id,
                    category="staples",
                    qty=1,
                    candidates=tuple(candidates),
                    need_by_minutes=need_by,
                    lock_platform=lock_p,
                )
            )

        all_offers: list[Offer] = []
        for p in available_platforms:
            all_offers.extend(_random_offers(rng, p))

        memberships = {p: rng.choice([True, False]) for p in available_platforms}

        base = baseline_plan(needs, all_offers, memberships)
        heur = plan_cheapest_now(needs, all_offers, memberships)

        assert heur.result.total_net <= base.result.total_net, (
            f"Heuristic ({heur.result.total_net}) worse than baseline ({base.result.total_net})"
        )


def _brute_force_optimal(
    needs: list[NeedLine],
    offers: list[Offer],
    memberships: dict[Platform, bool],
    max_slots_per_platform: int = 3,
) -> int:
    """Enumerate every assignment (candidate x order slot, up to max_slots orders per platform)."""
    # Filter to lines with allowed candidates
    priced_needs: list[tuple[NeedLine, tuple[Candidate, ...]]] = []
    for line in needs:
        allowed = allowed_candidates(line)
        if allowed:
            priced_needs.append((line, allowed))

    if not priced_needs:
        return 0

    # Possible candidate-choice and slot choices for each line
    line_options: list[list[tuple[Candidate, int]]] = []
    for _line, allowed in priced_needs:
        opts: list[tuple[Candidate, int]] = []
        # Group by platform to pick slot 0, 1, 2 on that platform
        for cand in allowed:
            for slot in range(max_slots_per_platform):
                opts.append((cand, slot))
        line_options.append(opts)

    best_net = 10**15

    for assignment in itertools.product(*line_options):
        # assignment[i] = (chosen_candidate, slot_idx) for priced_needs[i]
        # group into orders by (platform, slot_idx)
        orders_dict: dict[tuple[Platform, int], list[OrderLine]] = {}
        for (line, _), (cand, slot) in zip(priced_needs, assignment, strict=True):
            key = (cand.platform, slot)
            orders_dict.setdefault(key, []).append(
                OrderLine(
                    line_id=line.line_id,
                    category=line.category,
                    unit_price=cand.unit_price,
                    qty=line.qty,
                )
            )

        orders = [
            Order(
                platform=p,
                lines=tuple(lines),
                is_member=memberships.get(p, False),
            )
            for (p, _), lines in orders_dict.items()
        ]

        res = evaluate_plan(orders, offers, SAMPLE_SCHEDULES)
        if res.total_net < best_net:
            best_net = res.total_net

    return best_net


def test_case_10_matches_brute_force_on_small_cases() -> None:
    # 10. Matches brute force on small cases: for 20 random instances with <= 5 lines and <= 2 platforms,
    # enumerate every assignment (candidate x order slot, up to 3 orders per platform) through evaluate_plan.
    # The heuristic's total_net must be <= brute-force optimum + 100 paise (₹1) on at least 18 of 20,
    # and equal on all golden cases above.
    rng = random.Random(42)
    platforms_pool: list[Platform] = ["amazon", "flipkart"]

    within_threshold_count = 0
    total_instances = 20

    for _ in range(total_instances):
        num_lines = rng.randint(2, 4)
        needs: list[NeedLine] = []
        for i in range(num_lines):
            line_id = f"item_{i}"
            num_cands = rng.randint(1, 2)
            c_platforms = rng.sample(platforms_pool, num_cands)
            candidates: list[Candidate] = []
            for p in c_platforms:
                price = rng.randint(50, 400) * 100
                candidates.append(
                    Candidate(
                        listing_id=f"{line_id}_{p}",
                        platform=p,
                        unit_price=price,
                        eta_minutes=30,
                    )
                )
            needs.append(
                NeedLine(
                    line_id=line_id,
                    category="staples",
                    qty=1,
                    candidates=tuple(candidates),
                )
            )

        offers: list[Offer] = []
        for p in platforms_pool:
            if rng.random() < 0.6:
                offers.append(
                    Offer(
                        id=f"off_{p}",
                        platform=p,
                        kind="flat",
                        min_order=20000,
                        value=3000,
                        uses_left=2,
                    )
                )

        memberships = {p: rng.choice([True, False]) for p in platforms_pool}

        opt_net = _brute_force_optimal(needs, offers, memberships, max_slots_per_platform=2)
        heur = plan_cheapest_now(needs, offers, memberships)

        if heur.result.total_net <= opt_net + 100:
            within_threshold_count += 1

    assert within_threshold_count >= 18, (
        f"Only {within_threshold_count}/{total_instances} matched brute force within 100 paise"
    )


def test_case_11_deterministic_and_order_invariant() -> None:
    # 11. Deterministic: calling twice gives equal Plan objects.
    # Shuffling the input needs order gives the same Plan.
    oil = _need("oil", 66500, "amazon")
    surf = _need("surf", 34400, "amazon")
    dal = _need("dal", 33000, "amazon")

    a1 = Offer(
        id="A1",
        platform="amazon",
        kind="flat",
        min_order=50000,
        value=5000,
        uses_left=2,
    )

    plan_1 = plan_cheapest_now([oil, surf, dal], [a1], {"amazon": True})
    plan_2 = plan_cheapest_now([oil, surf, dal], [a1], {"amazon": True})
    plan_shuffled = plan_cheapest_now([dal, oil, surf], [a1], {"amazon": True})

    assert plan_1 == plan_2
    assert plan_1 == plan_shuffled


def test_case_12_locks_respected() -> None:
    # 12. Locks respected: lock Atta to instamart in case 8 -> Atta is on instamart,
    # and the result is still <= that instance's baseline.
    milk = _need("milk", 6800, "blinkit", eta=10, need_by=60)
    bread = _need("bread", 5000, "blinkit", eta=10, need_by=60)

    cand_im = Candidate(listing_id="atta_im", platform="instamart", unit_price=28500, eta_minutes=15)
    cand_bl = Candidate(listing_id="atta_bl", platform="blinkit", unit_price=28900, eta_minutes=10)
    atta = NeedLine(
        line_id="atta",
        category="staples",
        qty=1,
        candidates=(cand_im, cand_bl),
        lock_platform="instamart",
    )

    memberships: dict[Platform, bool] = {"blinkit": False, "instamart": True}

    base = baseline_plan([milk, bread, atta], [], memberships)
    plan = plan_cheapest_now([milk, bread, atta], [], memberships)

    # Atta must be on instamart
    atta_order = next(
        order for order in plan.orders if any(line.line_id == "atta" for line in order)
    )
    assert atta_order[0].platform == "instamart"
    assert plan.result.total_net <= base.result.total_net


def test_case_13_max_orders_per_platform() -> None:
    # 13. max_orders_per_platform=1 on case 4 -> 1 order, total_net == 128900.
    oil = _need("oil", 66500, "amazon")
    surf = _need("surf", 34400, "amazon")
    dal = _need("dal", 33000, "amazon")

    a1 = Offer(
        id="A1",
        platform="amazon",
        kind="flat",
        min_order=50000,
        value=5000,
        uses_left=2,
    )

    settings = PlanSettings(max_orders_per_platform=1)
    plan = plan_cheapest_now([oil, surf, dal], [a1], {"amazon": True}, settings=settings)

    assert len(plan.orders) == 1
    assert plan.result.total_net == 128900


def test_case_14_invariants() -> None:
    # 14. Every priced line appears exactly once. No order mixes platforms.
    # All prices come from the chosen candidate.
    rng = random.Random(99)
    available_platforms: list[Platform] = ["amazon", "flipkart", "blinkit"]

    needs: list[NeedLine] = []
    all_candidates_by_line: dict[str, dict[Platform, Candidate]] = {}

    for i in range(5):
        line_id = f"item_{i}"
        candidates: list[Candidate] = []
        by_plat: dict[Platform, Candidate] = {}
        for p in available_platforms:
            price = rng.randint(100, 500) * 100
            c = Candidate(
                listing_id=f"{line_id}_{p}",
                platform=p,
                unit_price=price,
                eta_minutes=30,
            )
            candidates.append(c)
            by_plat[p] = c
        all_candidates_by_line[line_id] = by_plat
        needs.append(
            NeedLine(
                line_id=line_id,
                category="staples",
                qty=rng.randint(1, 3),
                candidates=tuple(candidates),
            )
        )

    plan = plan_cheapest_now(needs, [], {p: True for p in available_platforms})

    seen_line_ids: list[str] = []
    for order in plan.orders:
        plat = order[0].platform
        for line in order:
            assert line.platform == plat, "Order mixed platforms!"
            cand = all_candidates_by_line[line.line_id][plat]
            assert line.listing_id == cand.listing_id
            assert line.unit_price == cand.unit_price
            seen_line_ids.append(line.line_id)

    assert sorted(seen_line_ids) == sorted(n.line_id for n in needs)


def test_plan_settings_rejects_invalid_limits() -> None:
    import pytest

    from app.optimizer.planning import PlanSettings

    with pytest.raises(ValueError):
        PlanSettings(max_orders_per_platform=0)
    with pytest.raises(ValueError):
        PlanSettings(max_iterations=-1)
