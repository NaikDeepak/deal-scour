# Task: optimizer — pending basket + fillers ("Max savings")

**Assigned to:** agy  **Lead / reviewer:** claude  **Second review:** codex (read-only)
**Branch:** `feat/optimizer-pending` (from `main`, after `feat/optimizer-heuristic` is merged)  **Worktree:** `../deal-scour-wt-agy`

## Goal
Produce the **Max savings** plan. It may hold back **one** order as a *pending basket* that is short of an offer threshold,
and suggest **fillers** (things the user buys anyway) that close the shortfall. It's chosen only when it beats *Cheapest now*
after discounting the pending offer by confidence ρ. Implements `docs/BASKET_OPTIMIZER.md` §2 (ρ), §4 (gap is not cost), §7
(filler choice) and golden **Ex 2**.

## Files you may touch (nothing else)
- `backend/app/optimizer/pending.py` (new)
- `backend/tests/optimizer/test_pending.py` (new)

Use, but do not modify: `contract.py`, `offers.py`, `evaluate.py`, `planning.py`, `baseline.py`, `heuristic.py`.

## Runtime boundary
Pure Python, standard library, deterministic. `mypy --strict` + `ruff` clean.

## API to implement — `app/optimizer/pending.py`
```python
@dataclass(frozen=True)
class Filler:
    filler_id: str          # unique; used as PlannedLine.line_id when added
    listing_id: str
    platform: Platform
    category: str
    unit_price: Paise
    score: int              # regret-free score from BASKET_OPTIMIZER §7 (higher = better); computed by the caller

@dataclass(frozen=True)
class PendingSettings:
    max_filler_gap: Paise = 25000   # largest shortfall we try to close with fillers
    rho_bp: int = 8000              # confidence the pending basket completes (0..10000)
    min_gain: Paise = 1000          # Max savings must beat Cheapest now by at least this (₹10)
    max_subset_size: int = 3        # lines moved into the pending order: 1..max_subset_size
    # __post_init__: ValueError if max_filler_gap < 0, rho_bp not in 0..10000, min_gain < 0, max_subset_size < 1

@dataclass(frozen=True)
class PendingOrder:
    order_index: int                # index into SavingsPlan.plan.orders
    target_offer_id: str
    threshold: Paise                # the min_order (or tier min) being targeted
    shortfall: Paise                # threshold - eligible subtotal BEFORE fillers (> 0)
    fillers: tuple[Filler, ...]     # sorted by filler_id

@dataclass(frozen=True)
class SavingsPlan:
    plan: Plan                      # all orders; the pending order INCLUDES its filler lines; result = evaluate_plan of these orders
    pending: tuple[PendingOrder, ...]   # empty when Cheapest now wins
    filler_cost: Paise              # sum of filler unit prices included
    effective_cost: Paise           # plan.result.total_net - filler_cost   (fillers are bought anyway)
    score: Paise                    # effective_cost + (10000 - rho_bp) * pending_offer_value // 10000

def choose_fillers(pool: Sequence[Filler], platform: Platform, shortfall: Paise,
                   eligible_categories: frozenset[str] | None) -> tuple[Filler, ...] | None
    # Only fillers on `platform` whose category is eligible. Pick the subset whose total >= shortfall with the
    # SMALLEST overshoot; ties -> higher total score -> fewer items -> lexicographically smaller sorted filler_ids.
    # None if no subset reaches the shortfall. Exhaustive over at most 15 eligible fillers (take the 15 cheapest if more).

def plan_max_savings(needs, offers, memberships, fillers: Sequence[Filler],
                     schedules=SAMPLE_SCHEDULES, settings: PlanSettings = PlanSettings(),
                     pending_settings: PendingSettings = PendingSettings()) -> SavingsPlan
```

**Algorithm (follow this)**
1. `C = plan_cheapest_now(...)`. The no-pending answer is `SavingsPlan(plan=C, pending=(), filler_cost=0, effective_cost=C.result.total_net, score=C.result.total_net)`.
2. For every platform `p` that has at least one offer with a threshold (flat/pct_cap with `min_order > 0`, or tiered), and for every
   subset `S` of `C`'s lines on `p` with size 1..`max_subset_size`, where **every line in S has `need_by_minutes is None`**:
   - Remaining orders = `C`'s orders with S's lines removed (drop orders that become empty), unchanged otherwise.
   - For every such offer `f` on `p` (and, for tiered, every tier min): `threshold` = `f.min_order` (or the tier min). `eligible` = S's
     subtotal over `f.eligible_categories`. Skip unless `0 < threshold - eligible <= max_filler_gap`.
   - `fl = choose_fillers(fillers, p, threshold - eligible, f.eligible_categories)`. Skip if None.
   - Candidate orders = remaining + one new order on `p` with S's lines plus the fillers (as `PlannedLine`s, `line_id = filler_id`, qty 1).
     Score it with `evaluate_plan`. `pending_offer_value` = the effective value of the offers applied to the pending order in that evaluation.
     Discard the candidate if `f.id` is not among the offers applied to the pending order.
3. Choose the candidate with the lowest `score`. Tie-break by lower `effective_cost`, then fewer fillers, then lexicographically smaller
   (sorted S line_ids, offer id). Return it only if `score <= C.result.total_net - min_gain`. Otherwise return the no-pending answer.
4. Output orders in the heuristic's canonical order (platform, -subtotal, first line_id), with `order_index` pointing at the pending order.

## Test cases (write first)
Amazon is a member (no fees). A1 = flat ₹50 ≥ ₹500, amazon, `uses_left=2`, `value_type="amazon_pay"`.
Needs: Oil 66500 and Surf 34400, both amazon-only, no need_by. Fillers: Vim (19900, score 5) and Tea (24000, score 3), both amazon.

1. **Ex 2 golden:** `plan_max_savings` → one pending order with lines {Surf, Vim}. `target_offer_id == "A1"`, `threshold == 50000`,
   `shortfall == 15600`, fillers == (Vim,). `plan.result.total_net == 110800`, `filler_cost == 19900`, `effective_cost == 90900`,
   `score == 91900`. Cheapest now alone is 95900.
2. Surf has `need_by_minutes=60` → no pending, and the plan equals Cheapest now (95900).
3. Empty filler pool → no pending.
4. `max_filler_gap=10000` → no pending (shortfall 15600 is too big).
5. `rho_bp=0` → score 95900 is not ≤ 95900 − 1000 → no pending.
6. Fillers only on flipkart → no pending.
7. `choose_fillers`: shortfall 15600 with pool {A 8000, B 8000, C 19900} → (A, B) (overshoot 400 beats 4300).
8. `choose_fillers` tie on overshoot: two fillers at 20000, scores 1 and 4 → the score-4 one.
9. `choose_fillers` with `eligible_categories={"cleaning"}` ignores a "staples" filler even if cheaper.
10. A1 `uses_left=1` → no pending. Holding Surf can't earn a second use, so the candidate's pending order gets no A1, or the score isn't better.
11. Determinism: same input → equal `SavingsPlan`. Shuffled needs or fillers → same result.
12. Invariants on 30 random seeded instances: `score <= cheapest.total_net`. At most one pending order. Every need line appears exactly once.
    Filler lines appear only in the pending order. `effective_cost == plan.result.total_net - filler_cost`.
13. `PendingSettings` validation errors as listed.

## Done when
- [ ] All cases pass. The full suite passes 3× in a row. mypy and ruff are clean. Commit on `feat/optimizer-pending` (no push).
- [ ] `scripts/collab.sh handoff agy claude "feat/optimizer-pending · <done> · <tests> · <unsure>"` then `release`.

## Don'ts
No new dependencies. Only the two files above. Only one pending order per plan. No explanations or reasons text yet.
One command per call, foreground only.
