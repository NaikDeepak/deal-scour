import random

import pytest

from app.optimizer.contract import Offer
from app.optimizer.heuristic import plan_cheapest_now
from app.optimizer.pending import (
    Filler,
    PendingSettings,
    choose_fillers,
    plan_max_savings,
)
from app.optimizer.planning import Candidate, NeedLine
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


# ---------------------------------------------------------------------------
# Test Cases from Spec
# ---------------------------------------------------------------------------


def test_case_1_ex_2_golden() -> None:
    # 1. Ex 2 golden: plan_max_savings -> one pending order with lines {Surf, Vim}.
    # target_offer_id == "A1", threshold == 50000, shortfall == 15600, fillers == (Vim,).
    # plan.result.total_net == 110800, filler_cost == 19900, effective_cost == 90900,
    # score == 91900. Cheapest now alone is 95900.
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
    tea = Filler(
        filler_id="tea",
        listing_id="tea_amazon",
        platform="amazon",
        category="staples",
        unit_price=24000,
        score=3,
    )

    cheapest = plan_cheapest_now(
        needs=[oil, surf],
        offers=[a1],
        memberships={"amazon": True},
    )
    assert cheapest.result.total_net == 95900

    plan = plan_max_savings(
        needs=[oil, surf],
        offers=[a1],
        memberships={"amazon": True},
        fillers=[vim, tea],
    )

    assert len(plan.pending) == 1
    pend = plan.pending[0]
    assert pend.target_offer_id == "A1"
    assert pend.threshold == 50000
    assert pend.shortfall == 15600
    assert pend.fillers == (vim,)

    assert plan.plan.result.total_net == 110800
    assert plan.filler_cost == 19900
    assert plan.effective_cost == 90900
    assert plan.score == 91900

    pend_order = plan.plan.orders[pend.order_index]
    assert {pl.line_id for pl in pend_order} == {"surf", "vim"}


def test_case_2_surf_urgent_need_by_minutes() -> None:
    # 2. Surf has need_by_minutes=60 -> no pending, and the plan equals Cheapest now (95900).
    oil = _need("oil", 66500, "amazon", cat="staples")
    surf = _need("surf", 34400, "amazon", cat="cleaning", eta=30, need_by=60)

    a1 = Offer(
        id="A1",
        platform="amazon",
        kind="flat",
        min_order=50000,
        value=5000,
        uses_left=2,
        value_type="amazon_pay",
    )
    vim = Filler("vim", "vim_amazon", "amazon", "cleaning", 19900, 5)
    tea = Filler("tea", "tea_amazon", "amazon", "staples", 24000, 3)

    plan = plan_max_savings(
        needs=[oil, surf],
        offers=[a1],
        memberships={"amazon": True},
        fillers=[vim, tea],
    )

    assert len(plan.pending) == 0
    assert plan.plan.result.total_net == 95900
    assert plan.effective_cost == 95900
    assert plan.score == 95900


def test_case_3_empty_filler_pool() -> None:
    # 3. Empty filler pool -> no pending.
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

    plan = plan_max_savings(
        needs=[oil, surf],
        offers=[a1],
        memberships={"amazon": True},
        fillers=[],
    )

    assert len(plan.pending) == 0
    assert plan.plan.result.total_net == 95900


def test_case_4_max_filler_gap_too_small() -> None:
    # 4. max_filler_gap=10000 -> no pending (shortfall 15600 is too big).
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
    vim = Filler("vim", "vim_amazon", "amazon", "cleaning", 19900, 5)

    plan = plan_max_savings(
        needs=[oil, surf],
        offers=[a1],
        memberships={"amazon": True},
        fillers=[vim],
        pending_settings=PendingSettings(max_filler_gap=10000),
    )

    assert len(plan.pending) == 0
    assert plan.plan.result.total_net == 95900


def test_case_5_rho_zero_no_pending() -> None:
    # 5. rho_bp=0 -> score 95900 is not <= 95900 - 1000 -> no pending.
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
    vim = Filler("vim", "vim_amazon", "amazon", "cleaning", 19900, 5)

    plan = plan_max_savings(
        needs=[oil, surf],
        offers=[a1],
        memberships={"amazon": True},
        fillers=[vim],
        pending_settings=PendingSettings(rho_bp=0),
    )

    assert len(plan.pending) == 0
    assert plan.plan.result.total_net == 95900


def test_case_6_fillers_only_on_other_platform() -> None:
    # 6. Fillers only on flipkart -> no pending.
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
    vim_fk = Filler("vim_fk", "vim_fk_l", "flipkart", "cleaning", 19900, 5)

    plan = plan_max_savings(
        needs=[oil, surf],
        offers=[a1],
        memberships={"amazon": True},
        fillers=[vim_fk],
    )

    assert len(plan.pending) == 0
    assert plan.plan.result.total_net == 95900


def test_case_7_choose_fillers_overshoot() -> None:
    # 7. choose_fillers: shortfall 15600 with pool {A 8000, B 8000, C 19900}
    # -> (A, B) (overshoot 400 beats 4300).
    fa = Filler("A", "A_l", "amazon", "staples", 8000, 1)
    fb = Filler("B", "B_l", "amazon", "staples", 8000, 1)
    fc = Filler("C", "C_l", "amazon", "staples", 19900, 1)

    chosen = choose_fillers([fa, fb, fc], "amazon", 15600, None)
    assert chosen == (fa, fb)


def test_case_8_choose_fillers_tie_on_overshoot() -> None:
    # 8. choose_fillers tie on overshoot: two fillers at 20000, scores 1 and 4 -> the score-4 one.
    f1 = Filler("F1", "F1_l", "amazon", "staples", 20000, 1)
    f2 = Filler("F2", "F2_l", "amazon", "staples", 20000, 4)

    chosen = choose_fillers([f1, f2], "amazon", 15600, None)
    assert chosen == (f2,)


def test_case_9_choose_fillers_category_eligibility() -> None:
    # 9. choose_fillers with eligible_categories={"cleaning"} ignores a "staples" filler even if cheaper.
    f_cheap = Filler("cheap", "cheap_l", "amazon", "staples", 16000, 5)
    f_clean = Filler("clean", "clean_l", "amazon", "cleaning", 19900, 1)

    chosen = choose_fillers([f_cheap, f_clean], "amazon", 15600, frozenset({"cleaning"}))
    assert chosen == (f_clean,)


def test_case_10_uses_exhausted_no_pending() -> None:
    # 10. A1 uses_left=1 -> no pending. Holding Surf can't earn a second use, so candidate's
    # pending order gets no A1, or the score isn't better.
    oil = _need("oil", 66500, "amazon", cat="staples")
    surf = _need("surf", 34400, "amazon", cat="cleaning")

    a1_one_use = Offer(
        id="A1",
        platform="amazon",
        kind="flat",
        min_order=50000,
        value=5000,
        uses_left=1,
        value_type="amazon_pay",
    )
    vim = Filler("vim", "vim_amazon", "amazon", "cleaning", 19900, 5)

    plan = plan_max_savings(
        needs=[oil, surf],
        offers=[a1_one_use],
        memberships={"amazon": True},
        fillers=[vim],
    )

    assert len(plan.pending) == 0
    assert plan.plan.result.total_net == 95900


def test_case_11_determinism() -> None:
    # 11. Determinism: same input -> equal SavingsPlan. Shuffled needs or fillers -> same result.
    oil = _need("oil", 66500, "amazon", cat="staples")
    surf = _need("surf", 34400, "amazon", cat="cleaning")
    a1 = Offer("A1", "amazon", "flat", min_order=50000, value=5000, uses_left=2, value_type="amazon_pay")
    vim = Filler("vim", "vim_l", "amazon", "cleaning", 19900, 5)
    tea = Filler("tea", "tea_l", "amazon", "staples", 24000, 3)

    plan1 = plan_max_savings([oil, surf], [a1], {"amazon": True}, [vim, tea])
    plan2 = plan_max_savings([surf, oil], [a1], {"amazon": True}, [tea, vim])
    assert plan1 == plan2


def test_case_12_invariants_random_instances() -> None:
    # 12. Invariants on 30 random seeded instances:
    # score <= cheapest.total_net. At most one pending order. Every need line appears exactly once.
    # Filler lines appear only in the pending order. effective_cost == plan.result.total_net - filler_cost.
    rng = random.Random(42)
    platforms: list[Platform] = ["amazon", "flipkart", "blinkit", "instamart", "zepto"]
    categories = ["staples", "cleaning", "dairy", "snacks"]

    for _ in range(30):
        # Generate 2 to 6 needs
        num_needs = rng.randint(2, 6)
        needs: list[NeedLine] = []
        for n_idx in range(num_needs):
            cands: list[Candidate] = []
            num_cands = rng.randint(1, 3)
            chosen_plats = rng.sample(platforms, num_cands)
            for p in chosen_plats:
                cands.append(
                    Candidate(
                        listing_id=f"n{n_idx}_{p}",
                        platform=p,
                        unit_price=rng.randint(5000, 50000),
                        eta_minutes=rng.choice([30, 120, 1440]),
                    )
                )
            need_by = rng.choice([None, None, 180, 1440])
            needs.append(
                NeedLine(
                    line_id=f"need_{n_idx}",
                    category=rng.choice(categories),
                    qty=1,
                    candidates=tuple(cands),
                    need_by_minutes=need_by,
                )
            )

        # Generate 1 to 3 offers
        num_offers = rng.randint(1, 3)
        offers: list[Offer] = []
        for o_idx in range(num_offers):
            plat = rng.choice(platforms)
            kind = rng.choice(["flat", "tiered"])
            if kind == "flat":
                offers.append(
                    Offer(
                        id=f"OFFER_{o_idx}",
                        platform=plat,
                        kind="flat",
                        min_order=rng.choice([30000, 50000, 80000]),
                        value=rng.choice([3000, 5000, 10000]),
                        uses_left=rng.choice([1, 2]),
                    )
                )
            else:
                offers.append(
                    Offer(
                        id=f"TIERED_{o_idx}",
                        platform=plat,
                        kind="tiered",
                        tiers=((40000, 4000), (80000, 9000)),
                        uses_left=rng.choice([1, 2]),
                    )
                )

        # Generate 0 to 5 fillers
        num_fillers = rng.randint(0, 5)
        fillers: list[Filler] = []
        for f_idx in range(num_fillers):
            fillers.append(
                Filler(
                    filler_id=f"filler_{f_idx}",
                    listing_id=f"fl_{f_idx}",
                    platform=rng.choice(platforms),
                    category=rng.choice(categories),
                    unit_price=rng.randint(2000, 25000),
                    score=rng.randint(-2, 10),
                )
            )

        memberships = {p: rng.choice([True, False]) for p in platforms}

        cheapest = plan_cheapest_now(needs, offers, memberships)
        savings = plan_max_savings(needs, offers, memberships, fillers)

        # Invariant 1: score <= cheapest.total_net
        assert savings.score <= cheapest.result.total_net

        # Invariant 2: at most one pending order
        assert len(savings.pending) <= 1

        # Invariant 3: effective_cost == plan.result.total_net - filler_cost
        assert savings.effective_cost == savings.plan.result.total_net - savings.filler_cost

        # Invariant 4: Every need line appears exactly once in placed orders + unpriced
        all_plan_lines = [pl.line_id for o in savings.plan.orders for pl in o]
        filler_ids = {f.filler_id for f in fillers}
        need_lines_in_plan = [lid for lid in all_plan_lines if lid not in filler_ids]
        assert len(need_lines_in_plan) + len(savings.plan.unpriced) == len(needs)
        assert set(need_lines_in_plan) | set(savings.plan.unpriced) == {n.line_id for n in needs}

        # Invariant 5: Filler lines appear only in the pending order
        if len(savings.pending) == 1:
            pend = savings.pending[0]
            assert 0 <= pend.order_index < len(savings.plan.orders)
            pend_order = savings.plan.orders[pend.order_index]
            pend_filler_ids = {f.filler_id for f in pend.fillers}
            order_filler_ids = {pl.line_id for pl in pend_order if pl.line_id in filler_ids}
            assert order_filler_ids == pend_filler_ids
            # Filler lines must not appear in any other order
            for o_idx, o in enumerate(savings.plan.orders):
                if o_idx != pend.order_index:
                    assert not any(pl.line_id in filler_ids for pl in o)
        else:
            assert not any(pl.line_id in filler_ids for o in savings.plan.orders for pl in o)
            assert savings.filler_cost == 0
            assert savings.effective_cost == savings.plan.result.total_net
            assert savings.score == savings.plan.result.total_net


def test_case_13_pending_settings_validation() -> None:
    # 13. PendingSettings validation errors as listed.
    with pytest.raises(ValueError, match="max_filler_gap"):
        PendingSettings(max_filler_gap=-1)

    with pytest.raises(ValueError, match="rho_bp"):
        PendingSettings(rho_bp=-1)

    with pytest.raises(ValueError, match="rho_bp"):
        PendingSettings(rho_bp=10001)

    with pytest.raises(ValueError, match="min_gain"):
        PendingSettings(min_gain=-1)

    with pytest.raises(ValueError, match="max_subset_size"):
        PendingSettings(max_subset_size=0)

    # Boolean type guard checks
    with pytest.raises(ValueError):
        PendingSettings(max_filler_gap=True)  # type: ignore[arg-type]

    with pytest.raises(ValueError):
        PendingSettings(rho_bp=True)  # type: ignore[arg-type]

    with pytest.raises(ValueError):
        PendingSettings(min_gain=True)  # type: ignore[arg-type]

    with pytest.raises(ValueError):
        PendingSettings(max_subset_size=True)  # type: ignore[arg-type]


def test_choose_fillers_pool_larger_than_15() -> None:
    # Pool with 20 fillers: the 15 cheapest should be considered
    pool = [
        Filler(f"f_{i:02d}", f"l_{i}", "amazon", "staples", (i + 1) * 1000, 1)
        for i in range(20)
    ]
    # Shortfall = 1000: f_00 (1000) alone satisfies it
    chosen = choose_fillers(pool, "amazon", 1000, None)
    assert chosen is not None
    assert len(chosen) == 1
    assert chosen[0].filler_id == "f_00"

    # Shortfall = 15000: f_14 (15000) from the 15 cheapest
    chosen = choose_fillers(pool, "amazon", 15000, None)
    assert chosen is not None
    assert sum(f.unit_price for f in chosen) == 15000


def test_choose_fillers_shortfall_zero_or_negative() -> None:
    pool = [Filler("f1", "l1", "amazon", "staples", 5000, 1)]
    assert choose_fillers(pool, "amazon", 0, None) == ()
    assert choose_fillers(pool, "amazon", -100, None) == ()


def test_choose_fillers_no_subset_reaches_shortfall() -> None:
    pool = [Filler("f1", "l1", "amazon", "staples", 5000, 1)]
    assert choose_fillers(pool, "amazon", 10000, None) is None


def test_choose_fillers_fewer_items_tie_break() -> None:
    # 2 items of 10000 (score 5 each, total score 10) vs 1 item of 20000 (score 10)
    # Both have overshoot 0 for shortfall 20000, both have score 10
    # Fewer items (1 vs 2) wins
    f_single = Filler("f_single", "l1", "amazon", "staples", 20000, 10)
    f_a = Filler("f_a", "l2", "amazon", "staples", 10000, 5)
    f_b = Filler("f_b", "l3", "amazon", "staples", 10000, 5)
    chosen = choose_fillers([f_single, f_a, f_b], "amazon", 20000, None)
    assert chosen == (f_single,)


def test_filler_validation() -> None:
    with pytest.raises(ValueError):
        Filler("f1", "l1", "amazon", "staples", -100, 1)
    with pytest.raises(ValueError):
        Filler("f1", "l1", "amazon", "staples", True, 1)  # type: ignore[arg-type]


def test_tiered_offer_pending_order() -> None:
    # Need ₹350, tiered offer ₹75 off ≥ ₹500, ₹150 off ≥ ₹1000 (uses=1)
    # Filler pool has ₹180 item -> 350 + 180 = 530 reaches first tier (500)
    item = _need("item", 35000, "amazon")
    tiered = Offer(
        id="T1",
        platform="amazon",
        kind="tiered",
        tiers=((50000, 7500), (100000, 15000)),
        uses_left=1,
    )
    filler = Filler("fl1", "fl1_l", "amazon", "staples", 18000, 5)

    plan = plan_max_savings(
        needs=[item],
        offers=[tiered],
        memberships={"amazon": True},
        fillers=[filler],
    )

    assert len(plan.pending) == 1
    pend = plan.pending[0]
    assert pend.target_offer_id == "T1"
    assert pend.threshold == 50000
    assert pend.shortfall == 15000
    assert pend.fillers == (filler,)
    # Subtotal = 35000 + 18000 = 53000 -> T1 applied (7500 off) -> net = 45500
    assert plan.plan.result.total_net == 45500
    assert plan.filler_cost == 18000
    assert plan.effective_cost == 27500

