from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from app.core.money import Paise, format_inr
from app.optimizer.contract import Offer
from app.optimizer.offers import face_value
from app.optimizer.pending import PendingOrder
from app.optimizer.planning import Plan
from app.pricing.fee_schedules import Platform

ReasonCode = Literal[
    "SPLIT_FOR_SLOT",
    "DEAD_WEIGHT",
    "MOVED_PLATFORM",
    "PENDING_SHORT",
    "FILLER_SUGGEST",
    "USES_EXHAUSTED",
]

REASON_CODE_ORDER: dict[ReasonCode, int] = {
    "SPLIT_FOR_SLOT": 0,
    "DEAD_WEIGHT": 1,
    "MOVED_PLATFORM": 2,
    "PENDING_SHORT": 3,
    "FILLER_SUGGEST": 4,
    "USES_EXHAUSTED": 5,
}


@dataclass(frozen=True)
class Reason:
    code: ReasonCode
    platform: Platform
    amount: Paise  # rupee impact as defined per code below (>= 0)
    line_ids: tuple[str, ...]  # sorted
    text: str  # rendered with format_inr, exact templates below

    def __post_init__(self) -> None:
        if self.amount < 0:
            raise ValueError(f"amount must be non-negative, got {self.amount}")
        if not isinstance(self.line_ids, tuple) or list(self.line_ids) != sorted(self.line_ids):
            object.__setattr__(self, "line_ids", tuple(sorted(self.line_ids)))


def _reason_sort_key(r: Reason) -> tuple[int, str, tuple[str, ...], str]:
    return (REASON_CODE_ORDER[r.code], r.platform, r.line_ids, r.text)


def explain(
    plan: Plan,
    baseline: Plan,
    offers: Sequence[Offer],
    pending: Sequence[PendingOrder] = (),
) -> tuple[Reason, ...]:
    if not plan.orders:
        return ()

    reasons: list[Reason] = []

    # 1. SPLIT_FOR_SLOT
    # Platform p has 2+ orders in plan, more than in baseline, and plan's total offer value on p > baseline's.
    plan_platforms = {order[0].platform for order in plan.orders}
    for p in sorted(plan_platforms):
        plan_orders_on_p = [o for o in plan.orders if o[0].platform == p]
        base_orders_on_p = [o for o in baseline.orders if o[0].platform == p]
        n = len(plan_orders_on_p)
        n_base = len(base_orders_on_p)

        plan_val_on_p = sum(
            a.effective_value
            for o_res in plan.result.orders
            if o_res.platform == p
            for a in o_res.applied
        )
        base_val_on_p = sum(
            a.effective_value
            for o_res in baseline.result.orders
            if o_res.platform == p
            for a in o_res.applied
        )

        if n >= 2 and n > n_base and plan_val_on_p > base_val_on_p:
            amount = plan_val_on_p - base_val_on_p
            line_ids = tuple(sorted(pline.line_id for o in plan_orders_on_p for pline in o))
            text = f"Split {p.capitalize()} into {n} orders to earn {format_inr(amount)} more in offers."
            reasons.append(
                Reason(
                    code="SPLIT_FOR_SLOT",
                    platform=p,
                    amount=amount,
                    line_ids=line_ids,
                    text=text,
                )
            )

    # 2. DEAD_WEIGHT
    # For an order in plan that has a flat offer f applied, where subtotal - f.min_order >= f.min_order
    # and f.uses_left > the number of plan orders using f. amount = f.value.
    offers_by_id = {o.id: o for o in offers}
    offer_use_count: dict[str, int] = {}
    for o_res in plan.result.orders:
        for a in o_res.applied:
            offer_use_count[a.offer_id] = offer_use_count.get(a.offer_id, 0) + 1

    for order, o_res in zip(plan.orders, plan.result.orders, strict=True):
        subtotal = o_res.subtotal
        for a in o_res.applied:
            f = offers_by_id.get(a.offer_id)
            if f is not None and f.kind == "flat":
                excess = subtotal - f.min_order
                if excess >= f.min_order and f.uses_left > offer_use_count.get(f.id, 0):
                    amount = f.value
                    line_ids = tuple(sorted(pline.line_id for pline in order))
                    text = (
                        f"{format_inr(excess)} above the {format_inr(f.min_order)} threshold "
                        f"earns nothing. Split it to earn another {format_inr(f.value)}."
                    )
                    reasons.append(
                        Reason(
                            code="DEAD_WEIGHT",
                            platform=order[0].platform,
                            amount=amount,
                            line_ids=line_ids,
                            text=text,
                        )
                    )

    # 3. MOVED_PLATFORM
    # A line whose platform in plan differs from its platform in baseline.
    # amount = plan unit_price x qty - baseline unit_price x qty (may be 0. Use 0 if negative).
    baseline_lines = {
        pline.line_id: pline
        for order in baseline.orders
        for pline in order
    }
    for order in plan.orders:
        for pline in order:
            if pline.line_id in baseline_lines:
                base_line = baseline_lines[pline.line_id]
                if pline.platform != base_line.platform:
                    diff = (pline.unit_price * pline.qty) - (base_line.unit_price * base_line.qty)
                    amount = max(0, diff)
                    plat_cap = pline.platform.capitalize()
                    if amount == 0:
                        text = f"{pline.line_id} moved to {plat_cap} to save on fees or unlock an offer."
                    else:
                        text = (
                            f"{pline.line_id} moved to {plat_cap}: "
                            f"{format_inr(amount)} dearer, but the plan costs less overall."
                        )
                    reasons.append(
                        Reason(
                            code="MOVED_PLATFORM",
                            platform=pline.platform,
                            amount=amount,
                            line_ids=(pline.line_id,),
                            text=text,
                        )
                    )

    # 4. PENDING_SHORT
    # amount = shortfall, line_ids = the pending order's non-filler lines.
    for pend in pending:
        pend_order = plan.orders[pend.order_index]
        p = pend_order[0].platform
        filler_ids = {f.filler_id for f in pend.fillers}
        non_filler_lines = tuple(
            sorted(pline.line_id for pline in pend_order if pline.line_id not in filler_ids)
        )
        plat_cap = p.capitalize()
        text = (
            f"Holding a {plat_cap} basket: "
            f"{format_inr(pend.shortfall)} short of the {format_inr(pend.threshold)} offer threshold."
        )
        reasons.append(
            Reason(
                code="PENDING_SHORT",
                platform=p,
                amount=pend.shortfall,
                line_ids=non_filler_lines,
                text=text,
            )
        )

    # 5. FILLER_SUGGEST
    # amount = filler.unit_price, line_ids = (filler_id,).
    for pend in pending:
        for filler in pend.fillers:
            text = f"Add {filler.filler_id} ({format_inr(filler.unit_price)}) to complete it."
            reasons.append(
                Reason(
                    code="FILLER_SUGGEST",
                    platform=filler.platform,
                    amount=filler.unit_price,
                    line_ids=(filler.filler_id,),
                    text=text,
                )
            )

    # 6. USES_EXHAUSTED
    # An offer f with every use applied in plan, while at least one other plan order on f.platform
    # would qualify for f (face_value > 0) but has no f. amount = 0, line_ids = that order's lines.
    for f in offers:
        if f.uses_left <= 0:
            continue
        applied_indices = [
            i
            for i, o_res in enumerate(plan.result.orders)
            if any(a.offer_id == f.id for a in o_res.applied)
        ]
        if len(applied_indices) == f.uses_left:
            for i, (order, o_res) in enumerate(zip(plan.orders, plan.result.orders, strict=True)):
                if i not in applied_indices and order[0].platform == f.platform:
                    sub = o_res.subtotal
                    if face_value(f, sub) > 0:
                        line_ids = tuple(sorted(pline.line_id for pline in order))
                        text = f"Only {f.uses_left} use(s) of {f.id} left, so this order can't get it too."
                        reasons.append(
                            Reason(
                                code="USES_EXHAUSTED",
                                platform=f.platform,
                                amount=0,
                                line_ids=line_ids,
                                text=text,
                            )
                        )

    reasons.sort(key=_reason_sort_key)
    return tuple(reasons)
