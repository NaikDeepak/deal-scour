import itertools
from collections import Counter
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass

from app.core.money import Paise
from app.optimizer.baseline import allowed_candidates, baseline_plan
from app.optimizer.contract import Offer, Order, OrderLine
from app.optimizer.evaluate import PlanResult, evaluate_plan
from app.optimizer.planning import (
    DEFAULT_PLAN_SETTINGS,
    Candidate,
    NeedLine,
    Plan,
    PlannedLine,
    PlanSettings,
)
from app.pricing.fee_schedules import SAMPLE_SCHEDULES, FeeSchedule, Platform


@dataclass(frozen=True)
class OrderState:
    platform: Platform
    line_ids: tuple[str, ...]


PlanState = tuple[OrderState, ...]
CanonicalKey = tuple[tuple[Platform, int, str], ...]
Score = tuple[Paise, int, CanonicalKey]


def _subtotal(
    order_state: OrderState,
    candidates_by_line_platform: Mapping[str, Mapping[Platform, Candidate]],
    priced_lines: Mapping[str, NeedLine],
) -> Paise:
    return sum(
        candidates_by_line_platform[lid][order_state.platform].unit_price
        * priced_lines[lid].qty
        for lid in order_state.line_ids
    )


def _make_canonical(
    orders: Sequence[OrderState],
    candidates_by_line_platform: Mapping[str, Mapping[Platform, Candidate]],
    priced_lines: Mapping[str, NeedLine],
) -> PlanState:
    non_empty: list[OrderState] = []
    for os in orders:
        if os.line_ids:
            sorted_lines = tuple(sorted(os.line_ids))
            non_empty.append(OrderState(os.platform, sorted_lines))

    # Canonical order: sorted by (platform, -subtotal, first line_id)
    non_empty.sort(
        key=lambda os: (
            os.platform,
            -_subtotal(os, candidates_by_line_platform, priced_lines),
            os.line_ids[0],
        )
    )
    return tuple(non_empty)


def _canonical_key(
    state: PlanState,
    candidates_by_line_platform: Mapping[str, Mapping[Platform, Candidate]],
    priced_lines: Mapping[str, NeedLine],
) -> CanonicalKey:
    return tuple(
        (
            os.platform,
            -_subtotal(os, candidates_by_line_platform, priced_lines),
            os.line_ids[0],
        )
        for os in state
    )


def _evaluate_state(
    state: PlanState,
    candidates_by_line_platform: Mapping[str, Mapping[Platform, Candidate]],
    priced_lines: Mapping[str, NeedLine],
    offers: Sequence[Offer],
    memberships: Mapping[Platform, bool],
    schedules: Mapping[Platform, FeeSchedule],
) -> tuple[PlanResult, Score]:
    if not state:
        empty_res = evaluate_plan([], offers, schedules)
        return empty_res, (0, 0, ())

    eval_orders: list[Order] = []
    for os in state:
        platform = os.platform
        order_lines = tuple(
            OrderLine(
                line_id=lid,
                category=priced_lines[lid].category,
                unit_price=candidates_by_line_platform[lid][platform].unit_price,
                qty=priced_lines[lid].qty,
            )
            for lid in os.line_ids
        )
        eval_orders.append(
            Order(
                platform=platform,
                lines=order_lines,
                is_member=memberships.get(platform, False),
            )
        )

    res = evaluate_plan(eval_orders, offers, schedules)
    canon_key = _canonical_key(state, candidates_by_line_platform, priced_lines)
    score: Score = (res.total_net, len(state), canon_key)
    return res, score


def _generate_moves(
    cur_state: PlanState,
    candidates_by_line_platform: Mapping[str, Mapping[Platform, Candidate]],
    priced_lines: Mapping[str, NeedLine],
    max_orders_per_platform: int,
) -> Iterator[PlanState]:
    orders_count_by_platform: dict[Platform, int] = Counter(os.platform for os in cur_state)

    # 1. Move a single line to another existing order
    for i, order_i in enumerate(cur_state):
        for lid in order_i.line_ids:
            for j, order_j in enumerate(cur_state):
                if i == j:
                    continue
                target_platform = order_j.platform
                if target_platform in candidates_by_line_platform[lid]:
                    new_order_i_lines = tuple(x for x in order_i.line_ids if x != lid)
                    new_order_j_lines = tuple(sorted(order_j.line_ids + (lid,)))
                    new_state = []
                    for idx, os in enumerate(cur_state):
                        if idx == i:
                            if new_order_i_lines:
                                new_state.append(OrderState(os.platform, new_order_i_lines))
                        elif idx == j:
                            new_state.append(OrderState(os.platform, new_order_j_lines))
                        else:
                            new_state.append(os)
                    yield _make_canonical(new_state, candidates_by_line_platform, priced_lines)

    # 2. Move a single line into a new order
    for i, order_i in enumerate(cur_state):
        for lid in order_i.line_ids:
            for p in candidates_by_line_platform[lid]:
                net_change = 0 if (order_i.platform == p and len(order_i.line_ids) == 1) else 1
                if (
                    orders_count_by_platform.get(p, 0) + net_change <= max_orders_per_platform
                    and not (order_i.platform == p and len(order_i.line_ids) == 1)
                ):
                    new_order_i_lines = tuple(x for x in order_i.line_ids if x != lid)
                    new_state = []
                    for idx, os in enumerate(cur_state):
                        if idx == i:
                            if new_order_i_lines:
                                new_state.append(OrderState(os.platform, new_order_i_lines))
                        else:
                            new_state.append(os)
                    new_state.append(OrderState(p, (lid,)))
                    yield _make_canonical(new_state, candidates_by_line_platform, priced_lines)

    # 3. Move a pair of lines into a new order (handles threshold splitting)
    for i, order_i in enumerate(cur_state):
        if len(order_i.line_ids) >= 2:
            for lid1, lid2 in itertools.combinations(order_i.line_ids, 2):
                common_platforms = set(candidates_by_line_platform[lid1]).intersection(
                    candidates_by_line_platform[lid2]
                )
                for p in sorted(common_platforms):
                    net_change = (
                        0 if (order_i.platform == p and len(order_i.line_ids) == 2) else 1
                    )
                    if (
                        orders_count_by_platform.get(p, 0) + net_change <= max_orders_per_platform
                        and not (order_i.platform == p and len(order_i.line_ids) == 2)
                    ):
                        new_order_i_lines = tuple(
                            x for x in order_i.line_ids if x not in (lid1, lid2)
                        )
                        new_state = []
                        for idx, os in enumerate(cur_state):
                            if idx == i:
                                if new_order_i_lines:
                                    new_state.append(OrderState(os.platform, new_order_i_lines))
                            else:
                                new_state.append(os)
                        new_state.append(OrderState(p, (min(lid1, lid2), max(lid1, lid2))))
                        yield _make_canonical(
                            new_state, candidates_by_line_platform, priced_lines
                        )

    # 4. Swap two lines between orders
    for i in range(len(cur_state)):
        for j in range(i + 1, len(cur_state)):
            order_i = cur_state[i]
            order_j = cur_state[j]
            for lid_i in order_i.line_ids:
                if order_j.platform in candidates_by_line_platform[lid_i]:
                    for lid_j in order_j.line_ids:
                        if order_i.platform in candidates_by_line_platform[lid_j]:
                            new_i_lines = tuple(
                                sorted([x for x in order_i.line_ids if x != lid_i] + [lid_j])
                            )
                            new_j_lines = tuple(
                                sorted([x for x in order_j.line_ids if x != lid_j] + [lid_i])
                            )
                            new_state = []
                            for idx, os in enumerate(cur_state):
                                if idx == i:
                                    new_state.append(OrderState(os.platform, new_i_lines))
                                elif idx == j:
                                    new_state.append(OrderState(os.platform, new_j_lines))
                                else:
                                    new_state.append(os)
                            yield _make_canonical(
                                new_state, candidates_by_line_platform, priced_lines
                            )

    # 5. Merge two orders of the same platform
    for i in range(len(cur_state)):
        for j in range(i + 1, len(cur_state)):
            order_i = cur_state[i]
            order_j = cur_state[j]
            if order_i.platform == order_j.platform:
                merged_lines = tuple(sorted(order_i.line_ids + order_j.line_ids))
                new_state = []
                for idx, os in enumerate(cur_state):
                    if idx == i:
                        new_state.append(OrderState(os.platform, merged_lines))
                    elif idx == j:
                        continue
                    else:
                        new_state.append(os)
                yield _make_canonical(new_state, candidates_by_line_platform, priced_lines)

    # 6. Re-home all lines of an order to another platform
    for i, order_i in enumerate(cur_state):
        # find common platforms for all lines in order_i
        common = set(candidates_by_line_platform[order_i.line_ids[0]])
        for lid in order_i.line_ids[1:]:
            common = common.intersection(candidates_by_line_platform[lid])
        for target_p in sorted(common):
            if target_p == order_i.platform:
                continue
            # Option A: Merge into an existing order on target_p
            for j, order_j in enumerate(cur_state):
                if order_j.platform == target_p:
                    new_j_lines = tuple(sorted(order_j.line_ids + order_i.line_ids))
                    new_state = []
                    for idx, os in enumerate(cur_state):
                        if idx == i:
                            continue
                        elif idx == j:
                            new_state.append(OrderState(os.platform, new_j_lines))
                        else:
                            new_state.append(os)
                    yield _make_canonical(new_state, candidates_by_line_platform, priced_lines)

            # Option B: Re-home as new order on target_p
            if orders_count_by_platform.get(target_p, 0) + 1 <= max_orders_per_platform:
                new_state = []
                for idx, os in enumerate(cur_state):
                    if idx == i:
                        new_state.append(OrderState(target_p, order_i.line_ids))
                    else:
                        new_state.append(os)
                yield _make_canonical(new_state, candidates_by_line_platform, priced_lines)


def plan_cheapest_now(
    needs: Sequence[NeedLine],
    offers: Sequence[Offer],
    memberships: Mapping[Platform, bool],
    schedules: Mapping[Platform, FeeSchedule] = SAMPLE_SCHEDULES,
    settings: PlanSettings = DEFAULT_PLAN_SETTINGS,
) -> Plan:
    """Plan lines to be bought now with lowest total_net using deterministic local search."""
    # Deterministic input sorting
    sorted_needs = sorted(needs, key=lambda n: n.line_id)
    base = baseline_plan(sorted_needs, offers, memberships, schedules)

    if not base.orders:
        return base

    priced_lines: dict[str, NeedLine] = {}
    candidates_by_line_platform: dict[str, dict[Platform, Candidate]] = {}

    for line in sorted_needs:
        allowed = allowed_candidates(line)
        if allowed:
            priced_lines[line.line_id] = line
            c_map: dict[Platform, Candidate] = {}
            for c in allowed:
                if c.platform not in c_map:
                    c_map[c.platform] = c
            candidates_by_line_platform[line.line_id] = c_map

    # Convert baseline plan to initial OrderState list
    cur_orders: list[OrderState] = []
    for order in base.orders:
        platform = order[0].platform
        line_ids = tuple(sorted(pline.line_id for pline in order))
        cur_orders.append(OrderState(platform, line_ids))

    cur_state = _make_canonical(cur_orders, candidates_by_line_platform, priced_lines)
    cur_result, cur_score = _evaluate_state(
        cur_state,
        candidates_by_line_platform,
        priced_lines,
        offers,
        memberships,
        schedules,
    )

    # Cache evaluated states to avoid re-evaluating equivalent partitions
    evaluated_cache: dict[PlanState, tuple[PlanResult, Score]] = {cur_state: (cur_result, cur_score)}

    iteration = 0
    while iteration < settings.max_iterations:
        best_candidate_state: PlanState | None = None
        best_candidate_result: PlanResult | None = None
        best_candidate_score: Score | None = None

        seen_in_neighborhood: set[PlanState] = set()

        for move_state in _generate_moves(
            cur_state,
            candidates_by_line_platform,
            priced_lines,
            settings.max_orders_per_platform,
        ):
            if move_state in seen_in_neighborhood or move_state == cur_state:
                continue
            seen_in_neighborhood.add(move_state)

            if move_state in evaluated_cache:
                cand_result, cand_score = evaluated_cache[move_state]
            else:
                cand_result, cand_score = _evaluate_state(
                    move_state,
                    candidates_by_line_platform,
                    priced_lines,
                    offers,
                    memberships,
                    schedules,
                )
                evaluated_cache[move_state] = (cand_result, cand_score)

            # Check if this candidate improves upon cur_score
            # Strict improvement: lower total_net, or equal total_net with fewer orders
            is_better_than_current = (cand_score[0] < cur_score[0]) or (
                cand_score[0] == cur_score[0] and cand_score[1] < cur_score[1]
            )

            if is_better_than_current and (
                best_candidate_score is None or cand_score < best_candidate_score
            ):
                best_candidate_state = move_state
                best_candidate_result = cand_result
                best_candidate_score = cand_score

        if (
            best_candidate_state is not None
            and best_candidate_result is not None
            and best_candidate_score is not None
        ):
            cur_state = best_candidate_state
            cur_result = best_candidate_result
            cur_score = best_candidate_score
            iteration += 1
        else:
            # Local minimum reached
            break

    # Build canonical Plan output
    canonical_planned_orders: list[tuple[PlannedLine, ...]] = []
    for os in cur_state:
        platform = os.platform
        planned_lines = tuple(
            PlannedLine(
                line_id=lid,
                listing_id=candidates_by_line_platform[lid][platform].listing_id,
                platform=platform,
                unit_price=candidates_by_line_platform[lid][platform].unit_price,
                qty=priced_lines[lid].qty,
            )
            for lid in os.line_ids
        )
        canonical_planned_orders.append(planned_lines)

    return Plan(
        orders=tuple(canonical_planned_orders),
        result=cur_result,
        unpriced=base.unpriced,
    )
