# Task: optimizer — baseline + heuristic planner ("Cheapest now")

**Assigned to:** agy  **Lead / reviewer:** claude  **Second review:** codex (read-only)
**Branch:** `feat/optimizer-heuristic` (from `main`, after `feat/optimizer-evaluate` is merged)  **Worktree:** `../deal-scour-wt-agy`

## Goal
Given needs (each with candidate listings on one or more platforms), memberships and offers, choose **which platform each
line is bought on and how lines are split into orders**, so that the plan's `total_net` (scored by `evaluate_plan`) is as low as
possible, with every line bought **now** (no pending baskets yet; that's the next task). Also compute the **baseline** plan we
compare against. Implements `docs/BASKET_OPTIMIZER.md` §2 (baseline) and §5 steps 1–6, and turns Ex 1, 3, 4, 5, 6 into golden tests.

## Files you may touch (nothing else)
- `backend/app/optimizer/planning.py` (new): input types
- `backend/app/optimizer/baseline.py` (new)
- `backend/app/optimizer/heuristic.py` (new)
- `backend/tests/optimizer/test_baseline.py` (new)
- `backend/tests/optimizer/test_heuristic.py` (new)

Use, but do not modify: `app/optimizer/contract.py`, `offers.py`, `evaluate.py`, `app/pricing/*`, `app/core/money.py`.

## Runtime boundary
Pure Python, standard library only, deterministic (no `random` in library code. Tests may use `random.Random(seed)`).
`mypy --strict` and `ruff` clean.

## API to implement

### `app/optimizer/planning.py`
```python
@dataclass(frozen=True)
class Candidate:
    listing_id: str
    platform: Platform
    unit_price: Paise          # already membership-adjusted (pricing.landed.unit_price)
    eta_minutes: int

@dataclass(frozen=True)
class NeedLine:
    line_id: str
    category: str
    qty: int
    candidates: tuple[Candidate, ...]
    need_by_minutes: int | None = None     # candidate allowed only if eta_minutes <= need_by_minutes
    lock_platform: Platform | None = None  # if set, only candidates on this platform are allowed

@dataclass(frozen=True)
class PlanSettings:
    max_orders_per_platform: int = 4
    max_iterations: int = 300

@dataclass(frozen=True)
class PlannedLine:
    line_id: str
    listing_id: str
    platform: Platform
    unit_price: Paise
    qty: int

@dataclass(frozen=True)
class Plan:
    orders: tuple[tuple[PlannedLine, ...], ...]   # each inner tuple is one order; all lines in it share a platform
    result: PlanResult                            # evaluate_plan of exactly these orders
    unpriced: tuple[str, ...]                     # line_ids with no allowed candidate (sorted)
```

### `app/optimizer/baseline.py`
```python
def allowed_candidates(line: NeedLine) -> tuple[Candidate, ...]
    # filter by need_by and lock_platform; sorted by (unit_price, eta_minutes, listing_id)
def baseline_plan(needs, offers, memberships: Mapping[Platform, bool], schedules=SAMPLE_SCHEDULES) -> Plan
    # each line -> its first allowed candidate; ONE order per platform; evaluated with evaluate_plan
```

### `app/optimizer/heuristic.py`
```python
def plan_cheapest_now(needs, offers, memberships, schedules=SAMPLE_SCHEDULES,
                      settings: PlanSettings = PlanSettings()) -> Plan
```
Required behaviour (the method is your choice; the suggested approach is §5 of BASKET_OPTIMIZER.md):
- Start from the baseline. Improve with deterministic local search, scoring every candidate plan with `evaluate_plan`:
  **move** a line to another existing order (same or different platform, using that platform's allowed candidate),
  **move** a line into a new order (respect `max_orders_per_platform`), **swap** two lines between orders, **merge** two
  orders of the same platform. Accept only strict improvements in `total_net`. Stop when no move improves or after `max_iterations`.
- When `total_net` ties, prefer **fewer orders**, then the canonical ordering below.
- **Canonical output:** orders sorted by (platform, -subtotal, first line_id). Lines in an order sorted by line_id. Empty orders removed.
- Deterministic: the same input always gives the identical `Plan`.
- Guarantees: `plan.result.total_net <= baseline_plan(...).result.total_net`. Every priced line appears exactly once. No order mixes platforms.

## Test cases (write these first, make them fail, then implement)

Helper for tests: `need(id, price, platform, cat="staples", eta=1440)` builds a single-candidate `NeedLine`.
Amazon and Flipkart are member platforms (no fees) unless stated.

**baseline**
1. `allowed_candidates`: need_by 60 drops a 1440-min candidate. lock_platform keeps only that platform. Sort by price, then eta, then listing_id.
2. A line with no allowed candidate goes to `unpriced` and is not in any order.
3. Baseline puts all Amazon lines in one order: Ex 1 lines with A1 (flat ₹50 ≥ ₹500, uses 2) → `total_net == 128900`.

**heuristic: golden (BASKET_OPTIMIZER §6)**
4. Ex 1: Oil 66500, Surf 34400, Dal 33000 (amazon), A1 uses 2 → `total_net == 123900`, 2 orders, each subtotal ≥ 50000.
5. Ex 6: same, A1 uses 1 → `total_net == 128900` and **1 order** (fewer-orders tie-break).
6. Ex 3: flipkart lines 60000, 40000, 50000, 30000 (total 180000), B1 = pct_cap 1000 bp cap 10000 min 50000 group "bank" uses 2 → `total_net == 162000`.
7. Ex 4: flipkart lines 80000, 40000, 32000 (total 152000), C1 tiered ((99900, 7500), (149900, 15000)) uses 1 → `total_net == 137000`, 1 order.
8. Ex 5: blinkit is non-member, instamart is member. Milk: blinkit 6800, eta 10, need_by 60. Bread: blinkit 5000, eta 10, need_by 60. Atta: candidates instamart 28500 (eta 15) and blinkit 28900 (eta 10), no need_by. No offers → `total_net == 40700`, a single blinkit order. Baseline is `42800` (blinkit 11800 + 2500 fee, instamart 28500).

**heuristic: properties**
9. Never worse than baseline: on 50 random instances (seeded `random.Random(7)`, 3–7 lines, 1–3 platforms per line, prices 5000–90000, 0–2 random offers per platform), `heuristic.total_net <= baseline.total_net`.
10. Matches brute force on small cases: for 20 random instances with ≤ 5 lines and ≤ 2 platforms, enumerate every assignment (candidate × order slot, up to 3 orders per platform) through `evaluate_plan`. The heuristic's `total_net` must be ≤ brute-force optimum + 100 paise (₹1) on at least 18 of 20, and equal on all golden cases above.
11. Deterministic: calling twice gives equal `Plan` objects. Shuffling the input `needs` order gives the same `Plan`.
12. Locks respected: lock Atta to instamart in case 8 → Atta is on instamart, and the result is still ≤ that instance's baseline.
13. `max_orders_per_platform=1` on case 4 → 1 order, `total_net == 128900`.
14. Every priced line appears exactly once. No order mixes platforms. All prices come from the chosen candidate.

## Seams
None.

## Done when
- [ ] All cases pass. The full suite passes 3 runs in a row. mypy and ruff are clean.
- [ ] Commit on `feat/optimizer-heuristic` (no push).
- [ ] `scripts/collab.sh handoff agy claude "feat/optimizer-heuristic · <done> · <test result> · <anything unsure>"` then `release`.

## Don'ts
- No new dependencies (no OR-Tools). No pending baskets, fillers or explanations (later tasks).
- No edits outside the file list. One command per call, foreground only.
