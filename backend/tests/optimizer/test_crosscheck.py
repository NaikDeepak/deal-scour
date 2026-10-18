"""Brute-force cross-checks for the optimizer (ADR-023 regression net).

evaluate_plan's offer assignment must equal exhaustive search, and plan_cheapest_now must reach the exhaustive
optimum on small random instances. If these fail after a change, the change made the solver worse.
"""

import itertools
import random

from app.optimizer.baseline import allowed_candidates, baseline_plan
from app.optimizer.contract import Offer, Order, OrderLine
from app.optimizer.evaluate import evaluate_plan
from app.optimizer.heuristic import plan_cheapest_now
from app.optimizer.offers import effective_value, eligible_subtotal, face_value
from app.optimizer.planning import Candidate, NeedLine
from app.pricing.fee_schedules import Platform

PLATFORMS: list[Platform] = ["amazon", "flipkart", "blinkit", "instamart"]


def _brute_offer_value(orders: list[Order], offers: list[Offer]) -> int:
    total = 0
    for group in sorted({o.stack_group for o in offers}):
        group_offers = [o for o in offers if o.stack_group == group]
        best = 0
        for choice in itertools.product([None, *range(len(group_offers))], repeat=len(orders)):
            uses = [0] * len(group_offers)
            value = 0
            valid = True
            for order, c in zip(orders, choice, strict=True):
                if c is None:
                    continue
                offer = group_offers[c]
                face = (
                    face_value(offer, eligible_subtotal(offer, order))
                    if offer.platform == order.platform
                    else 0
                )
                if face <= 0:
                    valid = False
                    break
                uses[c] += 1
                value += effective_value(offer, face)
            if valid and all(u <= group_offers[i].uses_left for i, u in enumerate(uses)):
                best = max(best, value)
        total += best
    return total


def _random_offer(rng: random.Random, offer_id: str, platform: Platform) -> Offer:
    kind = rng.choice(["flat", "pct_cap", "tiered"])
    common = {
        "uses_left": rng.randint(0, 3),
        "stack_group": rng.choice(["platform_coupon", "bank"]),
        "value_type": rng.choice(["cash", "supercoins"]),
        "eligible_categories": rng.choice([None, frozenset({"dryfruits"})]),
    }
    if kind == "flat":
        return Offer(
            offer_id,
            platform,
            "flat",
            min_order=rng.randrange(20000, 120000, 5000),
            value=rng.randrange(2000, 15000, 500),
            **common,
        )  # type: ignore[arg-type]
    if kind == "pct_cap":
        return Offer(
            offer_id,
            platform,
            "pct_cap",
            min_order=rng.randrange(0, 80000, 5000),
            rate_bp=rng.choice([500, 1000, 1500]),
            cap=rng.choice([None, 5000, 10000]),
            **common,
        )  # type: ignore[arg-type]
    return Offer(
        offer_id, platform, "tiered", tiers=((50000, 4000), (100000, 9000), (150000, 16000)), **common
    )  # type: ignore[arg-type]


def test_evaluate_assignment_matches_brute_force() -> None:
    rng = random.Random(42)
    for n in range(150):
        orders = [
            Order(
                rng.choice(["amazon", "flipkart"]),
                tuple(
                    OrderLine(
                        f"l{n}{k}", rng.choice(["staples", "dryfruits"]), rng.randrange(5000, 90000, 100)
                    )
                    for k in range(rng.randint(1, 3))
                ),
                is_member=True,
            )
            for _ in range(rng.randint(1, 4))
        ]
        offers = [
            _random_offer(rng, f"o{i}", rng.choice(["amazon", "flipkart"])) for i in range(rng.randint(0, 4))
        ]
        assert evaluate_plan(orders, offers).total_offer_value == _brute_offer_value(orders, offers), n


def _brute_plan_net(
    needs: list[NeedLine], offers: list[Offer], members: dict[Platform, bool], slots: int
) -> int:
    options = [[(c, s) for c in allowed_candidates(n) for s in range(slots)] for n in needs]
    best: int | None = None
    for combo in itertools.product(*options):
        buckets: dict[tuple[Platform, int], list[OrderLine]] = {}
        for need, (cand, slot) in zip(needs, combo, strict=True):
            buckets.setdefault((cand.platform, slot), []).append(
                OrderLine(need.line_id, need.category, cand.unit_price, need.qty)
            )
        orders = [Order(p, tuple(lines), members[p]) for (p, _), lines in sorted(buckets.items())]
        net = evaluate_plan(orders, offers).total_net
        best = net if best is None else min(best, net)
    assert best is not None
    return best


def test_heuristic_reaches_brute_force_optimum() -> None:
    rng = random.Random(2026)
    for n in range(40):
        plats = rng.sample(PLATFORMS, rng.randint(1, 2))
        members: dict[Platform, bool] = {p: rng.random() < 0.5 for p in PLATFORMS}
        needs = [
            NeedLine(
                f"n{i}",
                rng.choice(["staples", "dryfruits"]),
                1,
                tuple(
                    Candidate(f"L{i}{p}", p, rng.randrange(5000, 90000, 100), rng.choice([10, 1440]))
                    for p in rng.sample(plats, rng.randint(1, len(plats)))
                ),
            )
            for i in range(rng.randint(2, 4))
        ]
        offers = []
        for j in range(rng.randint(0, 3)):
            p = rng.choice(plats)
            if rng.random() < 0.6:
                offers.append(
                    Offer(
                        f"o{j}",
                        p,
                        "flat",
                        min_order=rng.randrange(20000, 100000, 5000),
                        value=rng.randrange(2000, 10000, 500),
                        uses_left=rng.randint(1, 3),
                    )
                )
            else:
                offers.append(
                    Offer(
                        f"o{j}",
                        p,
                        "pct_cap",
                        min_order=rng.randrange(0, 60000, 5000),
                        rate_bp=1000,
                        cap=rng.choice([5000, 10000]),
                        uses_left=rng.randint(1, 2),
                        stack_group="bank",
                    )
                )
        heuristic = plan_cheapest_now(needs, offers, members).result.total_net
        assert heuristic <= baseline_plan(needs, offers, members).result.total_net, n
        # 4 lines can need at most 4 orders on one platform
        assert heuristic == _brute_plan_net(needs, offers, members, slots=4), n
