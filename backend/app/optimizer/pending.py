import itertools
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from app.core.money import Paise
from app.optimizer.contract import Offer, Order, OrderLine
from app.optimizer.evaluate import PlanResult, evaluate_plan
from app.optimizer.heuristic import plan_cheapest_now
from app.optimizer.planning import (
    DEFAULT_PLAN_SETTINGS,
    NeedLine,
    Plan,
    PlannedLine,
    PlanSettings,
)
from app.pricing.fee_schedules import SAMPLE_SCHEDULES, FeeSchedule, Platform


@dataclass(frozen=True)
class Filler:
    filler_id: str  # unique; used as PlannedLine.line_id when added
    listing_id: str
    platform: Platform
    category: str
    unit_price: Paise
    score: int  # regret-free score from BASKET_OPTIMIZER §7 (higher = better); computed by the caller

    def __post_init__(self) -> None:
        if isinstance(self.unit_price, bool) or not isinstance(self.unit_price, int) or self.unit_price < 0:
            raise ValueError(f"unit_price must be non-negative int paise, got {self.unit_price!r}")


@dataclass(frozen=True)
class PendingSettings:
    max_filler_gap: Paise = 25000  # largest shortfall we try to close with fillers
    rho_bp: int = 8000  # confidence the pending basket completes (0..10000)
    min_gain: Paise = 1000  # Max savings must beat Cheapest now by at least this (₹10)
    max_subset_size: int = 3  # lines moved into the pending order: 1..max_subset_size

    def __post_init__(self) -> None:
        if (
            isinstance(self.max_filler_gap, bool)
            or not isinstance(self.max_filler_gap, int)
            or self.max_filler_gap < 0
        ):
            raise ValueError(
                f"max_filler_gap must be non-negative int paise, got {self.max_filler_gap!r}"
            )
        if (
            isinstance(self.rho_bp, bool)
            or not isinstance(self.rho_bp, int)
            or not (0 <= self.rho_bp <= 10000)
        ):
            raise ValueError(f"rho_bp must be 0..10000, got {self.rho_bp!r}")
        if (
            isinstance(self.min_gain, bool)
            or not isinstance(self.min_gain, int)
            or self.min_gain < 0
        ):
            raise ValueError(f"min_gain must be non-negative int paise, got {self.min_gain!r}")
        if (
            isinstance(self.max_subset_size, bool)
            or not isinstance(self.max_subset_size, int)
            or self.max_subset_size < 1
        ):
            raise ValueError(f"max_subset_size must be >= 1, got {self.max_subset_size!r}")


DEFAULT_PENDING_SETTINGS = PendingSettings()


@dataclass(frozen=True)
class PendingOrder:
    order_index: int  # index into SavingsPlan.plan.orders
    target_offer_id: str
    threshold: Paise  # the min_order (or tier min) being targeted
    shortfall: Paise  # threshold - eligible subtotal BEFORE fillers (> 0)
    fillers: tuple[Filler, ...]  # sorted by filler_id

    def __post_init__(self) -> None:
        if not isinstance(self.fillers, tuple):
            object.__setattr__(
                self, "fillers", tuple(sorted(self.fillers, key=lambda f: f.filler_id))
            )
        else:
            object.__setattr__(
                self, "fillers", tuple(sorted(self.fillers, key=lambda f: f.filler_id))
            )


@dataclass(frozen=True)
class SavingsPlan:
    # all orders; the pending order INCLUDES its filler lines; result = evaluate_plan of these orders
    plan: Plan
    pending: tuple[PendingOrder, ...]  # empty when Cheapest now wins
    filler_cost: Paise  # sum of filler unit prices included
    effective_cost: Paise  # plan.result.total_net - filler_cost   (fillers are bought anyway)
    score: Paise  # effective_cost + (10000 - rho_bp) * pending_offer_value // 10000

    def __post_init__(self) -> None:
        if not isinstance(self.pending, tuple):
            object.__setattr__(self, "pending", tuple(self.pending))


@dataclass(frozen=True)
class _Candidate:
    orders: tuple[tuple[PlannedLine, ...], ...]
    result: PlanResult
    pending_order_idx: int
    target_offer_id: str
    threshold: Paise
    shortfall: Paise
    fillers: tuple[Filler, ...]
    filler_cost: Paise
    effective_cost: Paise
    score: Paise


def choose_fillers(
    pool: Sequence[Filler],
    platform: Platform,
    shortfall: Paise,
    eligible_categories: frozenset[str] | None,
) -> tuple[Filler, ...] | None:
    if shortfall <= 0:
        return ()

    eligible = [
        f
        for f in pool
        if f.platform == platform
        and (eligible_categories is None or f.category in eligible_categories)
    ]
    if not eligible:
        return None

    # Exhaustive over at most 15 eligible fillers (take the 15 cheapest if more)
    eligible.sort(key=lambda f: (f.unit_price, -f.score, f.filler_id))
    if len(eligible) > 15:
        eligible = eligible[:15]

    best_key: tuple[int, int, int, tuple[str, ...]] | None = None
    best_subset: tuple[Filler, ...] | None = None

    for r in range(1, len(eligible) + 1):
        for comb in itertools.combinations(eligible, r):
            tot = sum(f.unit_price for f in comb)
            if tot >= shortfall:
                overshoot = tot - shortfall
                tot_score = sum(f.score for f in comb)
                sorted_ids = tuple(sorted(f.filler_id for f in comb))
                key = (overshoot, -tot_score, r, sorted_ids)
                if best_key is None or key < best_key:
                    best_key = key
                    best_subset = comb

    if best_subset is None:
        return None

    return tuple(sorted(best_subset, key=lambda f: f.filler_id))


def _is_threshold_offer(offer: Offer, platform: Platform) -> bool:
    if offer.platform != platform or offer.uses_left <= 0:
        return False
    if offer.kind in ("flat", "pct_cap") and offer.min_order > 0:
        return True
    return bool(offer.kind == "tiered" and len(offer.tiers) > 0)


def plan_max_savings(
    needs: Sequence[NeedLine],
    offers: Sequence[Offer],
    memberships: Mapping[Platform, bool],
    fillers: Sequence[Filler],
    schedules: Mapping[Platform, FeeSchedule] = SAMPLE_SCHEDULES,
    settings: PlanSettings = DEFAULT_PLAN_SETTINGS,
    pending_settings: PendingSettings = DEFAULT_PENDING_SETTINGS,
) -> SavingsPlan:
    # 1. C = plan_cheapest_now(...)
    C = plan_cheapest_now(
        needs=needs,
        offers=offers,
        memberships=memberships,
        schedules=schedules,
        settings=settings,
    )
    no_pending = SavingsPlan(
        plan=C,
        pending=(),
        filler_cost=0,
        effective_cost=C.result.total_net,
        score=C.result.total_net,
    )

    if not C.orders:
        return no_pending

    needs_by_id = {n.line_id: n for n in needs}
    category_map: dict[str, str] = {n.line_id: n.category for n in needs}
    category_map.update({f.filler_id: f.category for f in fillers})

    platforms_in_c = sorted({pl.platform for order in C.orders for pl in order})

    best_key: tuple[Paise, Paise, int, tuple[str, ...], str, Paise] | None = None
    best_cand: _Candidate | None = None

    # 2. For every platform p that has at least one offer with a threshold
    for p in platforms_in_c:
        threshold_offers = [o for o in offers if _is_threshold_offer(o, p)]
        if not threshold_offers:
            continue
        threshold_offers.sort(key=lambda o: o.id)

        # Lines on p in C where need_by_minutes is None
        lines_on_p = [
            pline
            for order in C.orders
            for pline in order
            if pline.platform == p and needs_by_id[pline.line_id].need_by_minutes is None
        ]
        if not lines_on_p:
            continue
        lines_on_p.sort(key=lambda pline: pline.line_id)

        max_k = min(pending_settings.max_subset_size, len(lines_on_p))
        for subset_size in range(1, max_k + 1):
            for S_tuple in itertools.combinations(lines_on_p, subset_size):
                S = tuple(S_tuple)
                s_line_ids = {pline.line_id for pline in S}

                # Remaining orders = C's orders with S's lines removed (drop empty orders)
                remaining_orders: list[tuple[PlannedLine, ...]] = []
                for order in C.orders:
                    rem = tuple(pline for pline in order if pline.line_id not in s_line_ids)
                    if rem:
                        remaining_orders.append(rem)

                for f in threshold_offers:
                    if f.kind in ("flat", "pct_cap"):
                        thresholds = [f.min_order]
                    else:
                        thresholds = [min_ord for min_ord, _ in f.tiers if min_ord > 0]

                    for threshold in thresholds:
                        if f.eligible_categories is None:
                            eligible = sum(pline.unit_price * pline.qty for pline in S)
                        else:
                            eligible = sum(
                                pline.unit_price * pline.qty
                                for pline in S
                                if needs_by_id[pline.line_id].category in f.eligible_categories
                            )

                        shortfall = threshold - eligible
                        if not (0 < shortfall <= pending_settings.max_filler_gap):
                            continue

                        fl = choose_fillers(fillers, p, shortfall, f.eligible_categories)
                        if fl is None:
                            continue

                        filler_planned_lines = tuple(
                            PlannedLine(
                                line_id=filler.filler_id,
                                listing_id=filler.listing_id,
                                platform=p,
                                unit_price=filler.unit_price,
                                qty=1,
                            )
                            for filler in fl
                        )
                        pending_lines = tuple(
                            sorted(S + filler_planned_lines, key=lambda pline: pline.line_id)
                        )
                        pending_line_ids = {pline.line_id for pline in pending_lines}

                        # Canonical order of orders: (platform, -subtotal, first line_id)
                        cand_orders = list(remaining_orders) + [pending_lines]
                        cand_orders = [
                            tuple(sorted(order, key=lambda pline: pline.line_id))
                            for order in cand_orders
                        ]
                        cand_orders.sort(
                            key=lambda order: (
                                order[0].platform,
                                -sum(pline.unit_price * pline.qty for pline in order),
                                order[0].line_id,
                            )
                        )
                        canonical_orders = tuple(cand_orders)
                        pending_order_idx = next(
                            i
                            for i, order in enumerate(canonical_orders)
                            if {pline.line_id for pline in order} == pending_line_ids
                        )

                        # Evaluate with evaluate_plan
                        eval_orders: list[Order] = []
                        for order in canonical_orders:
                            order_lines = tuple(
                                OrderLine(
                                    line_id=pline.line_id,
                                    category=category_map[pline.line_id],
                                    unit_price=pline.unit_price,
                                    qty=pline.qty,
                                )
                                for pline in order
                            )
                            eval_orders.append(
                                Order(
                                    platform=order[0].platform,
                                    lines=order_lines,
                                    is_member=memberships.get(order[0].platform, False),
                                )
                            )

                        cand_result = evaluate_plan(
                            orders=eval_orders, offers=offers, schedules=schedules
                        )

                        pending_res = cand_result.orders[pending_order_idx]
                        applied_offer_ids = {a.offer_id for a in pending_res.applied}
                        if f.id not in applied_offer_ids:
                            continue

                        pending_offer_value = sum(a.effective_value for a in pending_res.applied)
                        filler_cost = sum(filler.unit_price for filler in fl)
                        effective_cost = cand_result.total_net - filler_cost
                        score = (
                            effective_cost
                            + (10000 - pending_settings.rho_bp) * pending_offer_value // 10000
                        )

                        cand_key = (
                            score,
                            effective_cost,
                            len(fl),
                            tuple(sorted(pline.line_id for pline in S)),
                            f.id,
                            threshold,
                        )

                        if best_key is None or cand_key < best_key:
                            best_key = cand_key
                            best_cand = _Candidate(
                                orders=canonical_orders,
                                result=cand_result,
                                pending_order_idx=pending_order_idx,
                                target_offer_id=f.id,
                                threshold=threshold,
                                shortfall=shortfall,
                                fillers=tuple(sorted(fl, key=lambda x: x.filler_id)),
                                filler_cost=filler_cost,
                                effective_cost=effective_cost,
                                score=score,
                            )

    # 3. Choose candidate with lowest score. Return only if score <= C.result.total_net - min_gain
    if (
        best_cand is not None
        and best_cand.score <= C.result.total_net - pending_settings.min_gain
    ):
        return SavingsPlan(
            plan=Plan(
                orders=best_cand.orders,
                result=best_cand.result,
                unpriced=C.unpriced,
            ),
            pending=(
                PendingOrder(
                    order_index=best_cand.pending_order_idx,
                    target_offer_id=best_cand.target_offer_id,
                    threshold=best_cand.threshold,
                    shortfall=best_cand.shortfall,
                    fillers=best_cand.fillers,
                ),
            ),
            filler_cost=best_cand.filler_cost,
            effective_cost=best_cand.effective_cost,
            score=best_cand.score,
        )

    return no_pending
