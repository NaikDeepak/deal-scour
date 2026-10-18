from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from app.core.money import Paise
from app.optimizer.baseline import allowed_candidates, baseline_plan
from app.optimizer.contract import Offer
from app.optimizer.explain import Reason, explain
from app.optimizer.heuristic import plan_cheapest_now
from app.optimizer.pending import (
    DEFAULT_PENDING_SETTINGS,
    Filler,
    PendingOrder,
    PendingSettings,
    plan_max_savings,
)
from app.optimizer.planning import (
    DEFAULT_PLAN_SETTINGS,
    NeedLine,
    Plan,
    PlannedLine,
    PlanSettings,
)
from app.pricing.fee_schedules import SAMPLE_SCHEDULES, FeeSchedule, Platform

PlanLabel = Literal["cheapest_now", "max_savings", "fastest"]


@dataclass(frozen=True)
class LabelledPlan:
    label: PlanLabel
    plan: Plan
    pending: tuple[PendingOrder, ...]
    effective_cost: Paise  # SavingsPlan.effective_cost for max_savings; plan.result.total_net otherwise
    savings_vs_baseline: Paise  # baseline.total_net - effective_cost (may be negative for fastest)
    reasons: tuple[Reason, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.pending, tuple):
            object.__setattr__(self, "pending", tuple(self.pending))
        if not isinstance(self.reasons, tuple):
            object.__setattr__(self, "reasons", tuple(self.reasons))


@dataclass(frozen=True)
class PlanSet:
    baseline: Plan
    plans: tuple[LabelledPlan, ...]  # order: cheapest_now, max_savings, fastest; duplicates removed

    def __post_init__(self) -> None:
        if not isinstance(self.plans, tuple):
            object.__setattr__(self, "plans", tuple(self.plans))


def plan(
    needs: Sequence[NeedLine],
    offers: Sequence[Offer],
    memberships: Mapping[Platform, bool],
    fillers: Sequence[Filler] = (),
    schedules: Mapping[Platform, FeeSchedule] = SAMPLE_SCHEDULES,
    settings: PlanSettings = DEFAULT_PLAN_SETTINGS,
    pending_settings: PendingSettings = DEFAULT_PENDING_SETTINGS,
) -> PlanSet:
    # 1. Baseline plan
    baseline = baseline_plan(
        needs=needs,
        offers=offers,
        memberships=memberships,
        schedules=schedules,
    )
    base_net = baseline.result.total_net

    included_plans: list[LabelledPlan] = []
    included_orders: list[tuple[tuple[PlannedLine, ...], ...]] = []

    # 2. Cheapest now
    cn_plan = plan_cheapest_now(
        needs=needs,
        offers=offers,
        memberships=memberships,
        schedules=schedules,
        settings=settings,
    )
    cn_effective = cn_plan.result.total_net
    cn_savings = base_net - cn_effective
    cn_reasons = explain(cn_plan, baseline, offers, pending=())
    cn_labelled = LabelledPlan(
        label="cheapest_now",
        plan=cn_plan,
        pending=(),
        effective_cost=cn_effective,
        savings_vs_baseline=cn_savings,
        reasons=cn_reasons,
    )
    included_plans.append(cn_labelled)
    included_orders.append(cn_plan.orders)

    # 3. Max savings: included only if it has a pending order
    ms_savings_plan = plan_max_savings(
        needs=needs,
        offers=offers,
        memberships=memberships,
        fillers=fillers,
        schedules=schedules,
        settings=settings,
        pending_settings=pending_settings,
    )
    if ms_savings_plan.pending and ms_savings_plan.plan.orders not in included_orders:
        ms_effective = ms_savings_plan.effective_cost
        ms_savings = base_net - ms_effective
        ms_reasons = explain(
            ms_savings_plan.plan,
            baseline,
            offers,
            pending=ms_savings_plan.pending,
        )
        ms_labelled = LabelledPlan(
            label="max_savings",
            plan=ms_savings_plan.plan,
            pending=ms_savings_plan.pending,
            effective_cost=ms_effective,
            savings_vs_baseline=ms_savings,
            reasons=ms_reasons,
        )
        included_plans.append(ms_labelled)
        included_orders.append(ms_savings_plan.plan.orders)

    # 4. Fastest: plan_cheapest_now on needs where each line keeps only candidates with minimum eta_minutes
    fastest_needs: list[NeedLine] = []
    for line in needs:
        allowed = allowed_candidates(line)
        if not allowed:
            fastest_needs.append(line)
            continue
        min_eta = min(c.eta_minutes for c in allowed)
        fastest_cands = tuple(c for c in allowed if c.eta_minutes == min_eta)
        fastest_needs.append(
            NeedLine(
                line_id=line.line_id,
                category=line.category,
                qty=line.qty,
                candidates=fastest_cands,
                need_by_minutes=line.need_by_minutes,
                lock_platform=line.lock_platform,
            )
        )

    fastest_plan = plan_cheapest_now(
        needs=fastest_needs,
        offers=offers,
        memberships=memberships,
        schedules=schedules,
        settings=settings,
    )

    # Dedup: leave out if its orders equal earlier included plan's orders (e.g. cheapest_now)
    if fastest_plan.orders not in included_orders:
        fastest_effective = fastest_plan.result.total_net
        fastest_savings = base_net - fastest_effective
        fastest_reasons = explain(fastest_plan, baseline, offers, pending=())
        fastest_labelled = LabelledPlan(
            label="fastest",
            plan=fastest_plan,
            pending=(),
            effective_cost=fastest_effective,
            savings_vs_baseline=fastest_savings,
            reasons=fastest_reasons,
        )
        included_plans.append(fastest_labelled)
        included_orders.append(fastest_plan.orders)

    return PlanSet(
        baseline=baseline,
        plans=tuple(included_plans),
    )
