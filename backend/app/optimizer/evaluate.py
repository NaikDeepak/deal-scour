from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from app.core.money import Paise
from app.optimizer.contract import Offer, Order
from app.optimizer.offers import effective_value, eligible_subtotal, face_value
from app.pricing.fee_schedules import SAMPLE_SCHEDULES, FeeBreakdown, FeeSchedule, Platform, order_fees


@dataclass(frozen=True)
class AppliedOffer:
    offer_id: str
    face_value: Paise
    effective_value: Paise


@dataclass(frozen=True)
class OrderResult:
    platform: Platform
    subtotal: Paise
    fees: FeeBreakdown
    applied: tuple[AppliedOffer, ...]  # sorted by offer_id
    net: Paise  # subtotal + fees.total - sum(effective_value)


@dataclass(frozen=True)
class PlanResult:
    orders: tuple[OrderResult, ...]  # same order as the input
    total_subtotal: Paise
    total_fees: Paise
    total_offer_value: Paise  # sum of effective values
    total_net: Paise


def _solve_stack_group(
    orders: Sequence[Order],
    group_offers: list[Offer],
) -> list[Offer | None]:
    """Solve offer-to-order assignment for a single stack group.

    Maximizes total effective value, tie-breaking by:
    1. Fewer total offer uses
    2. Order-by-order comparison where earlier orders getting an offer win,
       lower offer IDs win, and 'no offer' ranks after every offer ID.
    """
    n = len(orders)
    m = len(group_offers)
    if n == 0:
        return []
    if m == 0:
        return [None] * n

    # Sort offers by ID for deterministic indexing
    sorted_offers = sorted(group_offers, key=lambda o: o.id)

    # Precompute applicability and effective values for each (order, offer) pair
    # eligible_grid[i][j] = (face, eff) if applicable and face > 0 else None
    eligible_grid: list[list[tuple[Paise, Paise] | None]] = []
    for order in orders:
        row: list[tuple[Paise, Paise] | None] = []
        for offer in sorted_offers:
            if offer.platform == order.platform:
                sub = eligible_subtotal(offer, order)
                face = face_value(offer, sub)
                if face > 0:
                    eff = effective_value(offer, face)
                    row.append((face, eff))
                else:
                    row.append(None)
            else:
                row.append(None)
        eligible_grid.append(row)

    # Initial remaining uses
    init_rem = tuple(min(o.uses_left, n) for o in sorted_offers)

    # DP with memoization
    # memo[(order_idx, rem)] = (cand_key, cand_assignment)
    # cand_key = (-val, count, tokens)
    # tokens = tuple of (0, offer_id) or (1, "") for each order
    memo: dict[
        tuple[int, tuple[int, ...]],
        tuple[tuple[int, int, tuple[tuple[int, str], ...]], tuple[Offer | None, ...]],
    ] = {}

    def dp(
        order_idx: int,
        rem: tuple[int, ...],
    ) -> tuple[tuple[int, int, tuple[tuple[int, str], ...]], tuple[Offer | None, ...]]:
        if order_idx == n:
            return ((0, 0, ()), ())

        state = (order_idx, rem)
        if state in memo:
            return memo[state]

        # Option 0: No offer on this order
        none_token = (1, "")
        rest_key_none, rest_assign_none = dp(order_idx + 1, rem)
        best_key = (
            rest_key_none[0],
            rest_key_none[1],
            (none_token,) + rest_key_none[2],
        )
        best_assign: tuple[Offer | None, ...] = (None,) + rest_assign_none

        # Option j: Assign offer j
        for j, offer in enumerate(sorted_offers):
            if rem[j] > 0:
                cell = eligible_grid[order_idx][j]
                if cell is not None:
                    _, eff = cell
                    new_rem = rem[:j] + (rem[j] - 1,) + rem[j + 1 :]
                    rest_key, rest_assign = dp(order_idx + 1, new_rem)
                    cand_val = eff - rest_key[0]  # rest_key[0] is -rest_val
                    cand_count = 1 + rest_key[1]
                    cand_token = (0, offer.id)
                    cand_key = (-cand_val, cand_count, (cand_token,) + rest_key[2])
                    if cand_key < best_key:
                        best_key = cand_key
                        best_assign = (offer,) + rest_assign

        memo[state] = (best_key, best_assign)
        return memo[state]

    _, assignment = dp(0, init_rem)
    return list(assignment)


def evaluate_plan(
    orders: Sequence[Order],
    offers: Sequence[Offer],
    schedules: Mapping[Platform, FeeSchedule] = SAMPLE_SCHEDULES,
) -> PlanResult:
    """Evaluate an exact split of orders against available offers and fee schedules.

    Maximizes total effective offer value respecting stacking groups and usages,
    computes order-level fees, and calculates net totals.
    """
    # Validate offer IDs are unique
    seen_offer_ids: set[str] = set()
    for offer in offers:
        if offer.id in seen_offer_ids:
            raise ValueError(f"duplicate offer id: {offer.id}")
        seen_offer_ids.add(offer.id)

    if not orders:
        return PlanResult(
            orders=(),
            total_subtotal=0,
            total_fees=0,
            total_offer_value=0,
            total_net=0,
        )

    # Group offers by stack_group
    offers_by_group: dict[str, list[Offer]] = {}
    for offer in offers:
        if offer.uses_left > 0:
            offers_by_group.setdefault(offer.stack_group, []).append(offer)

    # For each order, collect applied offers across all stack groups
    applied_by_order: list[list[AppliedOffer]] = [[] for _ in range(len(orders))]

    for group_offers in offers_by_group.values():
        assignment = _solve_stack_group(orders, group_offers)
        for order_idx, assigned_offer in enumerate(assignment):
            if assigned_offer is not None:
                order = orders[order_idx]
                sub = eligible_subtotal(assigned_offer, order)
                face = face_value(assigned_offer, sub)
                eff = effective_value(assigned_offer, face)
                applied_by_order[order_idx].append(
                    AppliedOffer(
                        offer_id=assigned_offer.id,
                        face_value=face,
                        effective_value=eff,
                    )
                )

    # Build OrderResults
    order_results: list[OrderResult] = []
    for order_idx, order in enumerate(orders):
        schedule = schedules.get(order.platform, SAMPLE_SCHEDULES[order.platform])
        fees = order_fees(schedule, order.subtotal, order.is_member, order.surge)
        # Applied offers must be sorted by offer_id
        applied_sorted = tuple(sorted(applied_by_order[order_idx], key=lambda a: a.offer_id))
        order_eff_total = sum(a.effective_value for a in applied_sorted)
        net = order.subtotal + fees.total - order_eff_total

        order_results.append(
            OrderResult(
                platform=order.platform,
                subtotal=order.subtotal,
                fees=fees,
                applied=applied_sorted,
                net=net,
            )
        )

    total_subtotal = sum(r.subtotal for r in order_results)
    total_fees = sum(r.fees.total for r in order_results)
    total_offer_value = sum(a.effective_value for r in order_results for a in r.applied)
    total_net = total_subtotal + total_fees - total_offer_value

    return PlanResult(
        orders=tuple(order_results),
        total_subtotal=total_subtotal,
        total_fees=total_fees,
        total_offer_value=total_offer_value,
        total_net=total_net,
    )
