from collections.abc import Mapping, Sequence

from app.optimizer.contract import Offer, Order, OrderLine
from app.optimizer.evaluate import evaluate_plan
from app.optimizer.planning import Candidate, NeedLine, Plan, PlannedLine
from app.pricing.fee_schedules import SAMPLE_SCHEDULES, FeeSchedule, Platform


def allowed_candidates(line: NeedLine) -> tuple[Candidate, ...]:
    """Filter candidates by need_by and lock_platform; sort by (unit_price, eta_minutes, listing_id)."""
    allowed: list[Candidate] = []
    for cand in line.candidates:
        if line.need_by_minutes is not None and cand.eta_minutes > line.need_by_minutes:
            continue
        if line.lock_platform is not None and cand.platform != line.lock_platform:
            continue
        allowed.append(cand)

    allowed.sort(key=lambda c: (c.unit_price, c.eta_minutes, c.listing_id))
    return tuple(allowed)


def baseline_plan(
    needs: Sequence[NeedLine],
    offers: Sequence[Offer],
    memberships: Mapping[Platform, bool],
    schedules: Mapping[Platform, FeeSchedule] = SAMPLE_SCHEDULES,
) -> Plan:
    """Each line -> its first allowed candidate; ONE order per platform; evaluated with evaluate_plan."""
    sorted_needs = sorted(needs, key=lambda n: n.line_id)
    category_by_line = {n.line_id: n.category for n in sorted_needs}

    unpriced: list[str] = []
    lines_by_platform: dict[Platform, list[PlannedLine]] = {}

    for line in sorted_needs:
        allowed = allowed_candidates(line)
        if not allowed:
            unpriced.append(line.line_id)
            continue
        best_cand = allowed[0]
        planned_line = PlannedLine(
            line_id=line.line_id,
            listing_id=best_cand.listing_id,
            platform=best_cand.platform,
            unit_price=best_cand.unit_price,
            qty=line.qty,
        )
        lines_by_platform.setdefault(best_cand.platform, []).append(planned_line)

    order_tuples: list[tuple[PlannedLine, ...]] = []
    for lines in lines_by_platform.values():
        if lines:
            sorted_lines = tuple(sorted(lines, key=lambda pline: pline.line_id))
            order_tuples.append(sorted_lines)

    # Canonical order: sorted by (platform, -subtotal, first line_id)
    canonical_orders = tuple(
        sorted(
            order_tuples,
            key=lambda o: (o[0].platform, -sum(pline.unit_price * pline.qty for pline in o), o[0].line_id),
        )
    )

    evaluated_orders: list[Order] = []
    for o in canonical_orders:
        platform = o[0].platform
        order_lines = tuple(
            OrderLine(
                line_id=pline.line_id,
                category=category_by_line[pline.line_id],
                unit_price=pline.unit_price,
                qty=pline.qty,
            )
            for pline in o
        )
        evaluated_orders.append(
            Order(
                platform=platform,
                lines=order_lines,
                is_member=memberships.get(platform, False),
            )
        )

    result = evaluate_plan(evaluated_orders, offers, schedules)

    return Plan(
        orders=canonical_orders,
        result=result,
        unpriced=tuple(sorted(unpriced)),
    )
