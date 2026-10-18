# Task: optimizer — PlanSet (3 labelled plans) + reasons

**Assigned to:** agy  **Lead / reviewer:** claude  **Second review:** codex (read-only)
**Branch:** `feat/optimizer-planset` (from `main`, after `feat/optimizer-pending` is merged)  **Worktree:** `../deal-scour-wt-agy`

## Goal
One entry point `plan(...)` that returns the baseline plus up to three labelled plans (*Cheapest now*, *Max savings*, *Fastest*),
deduplicated, each with savings vs baseline and plain-English **reasons**. This is what the API and UI will show
(`docs/BASKET_OPTIMIZER.md` §8, §9; ADR-007).

## Files you may touch (nothing else)
- `backend/app/optimizer/explain.py` (new)
- `backend/app/optimizer/planset.py` (new)
- `backend/tests/optimizer/test_explain.py` (new)
- `backend/tests/optimizer/test_planset.py` (new)

Use, but do not modify: every other `app/optimizer/*` module, `app/core/money.py` (`format_inr`).

## Runtime boundary
Pure Python, standard library, deterministic. `mypy --strict` + `ruff` clean.

## API

### `app/optimizer/explain.py`
```python
ReasonCode = Literal["SPLIT_FOR_SLOT", "DEAD_WEIGHT", "MOVED_PLATFORM", "PENDING_SHORT", "FILLER_SUGGEST", "USES_EXHAUSTED"]

@dataclass(frozen=True)
class Reason:
    code: ReasonCode
    platform: Platform
    amount: Paise            # rupee impact as defined per code below (>= 0)
    line_ids: tuple[str, ...]  # sorted
    text: str                # rendered with format_inr, exact templates below

def explain(plan: Plan, baseline: Plan, offers: Sequence[Offer],
            pending: Sequence[PendingOrder] = ()) -> tuple[Reason, ...]
    # sorted by (code order as listed in ReasonCode, platform, line_ids)
```
Rules and **exact** text templates:
- **SPLIT_FOR_SLOT**: platform `p` has **2 or more** orders in `plan` and more than in `baseline`, and the plan's total offer value on `p` is greater than the baseline's.
  `amount` = plan offer value on p − baseline offer value on p. `line_ids` = all of the plan's lines on p.
  Text: `"Split {platform} into {n} orders to earn {amount} more in offers."`, where n is the number of plan orders on p.
- **DEAD_WEIGHT**: for an order in `plan` that has a **flat** offer `f` applied, whose lines can really be divided into two orders that both reach `f.min_order`
  and `f.uses_left` > the number of plan orders using `f`. `amount = f.value`.
  Text: `"{excess} above the {min} threshold earns nothing. Split it to earn another {value}."`, where excess = subtotal − min.
- **MOVED_PLATFORM**: a line whose platform in `plan` differs from its platform in `baseline`. `amount` = plan unit_price × qty −
  baseline unit_price × qty (may be 0. Use 0 if negative). Text: `"{line_id} moved to {platform}: {amount} dearer, but the plan costs less overall."`
  If amount == 0: `"{line_id} moved to {platform} to save on fees or unlock an offer."`
- **PENDING_SHORT** (one per PendingOrder): `amount = shortfall`, `line_ids` = the pending order's non-filler lines.
  Text: `"Holding a {platform} basket: {shortfall} short of the {threshold} offer threshold."`
- **FILLER_SUGGEST** (one per filler of each PendingOrder): `amount = filler.unit_price`, `line_ids = (filler_id,)`.
  Text: `"Add {filler_id} ({price}) to complete it."`
- **USES_EXHAUSTED**: an offer `f` with every use applied in `plan`, while at least one other plan order on `f.platform` would qualify
  for `f` (face_value > 0) but has no `f`. `amount = 0`, `line_ids` = that order's lines.
  Text: `"Only {uses} use(s) of {offer_id} left, so this order can't get it too."`

`{platform}` is rendered capitalised: Amazon, Flipkart, Blinkit, Instamart, Zepto. Money is rendered with `format_inr`.

### `app/optimizer/planset.py`
```python
PlanLabel = Literal["cheapest_now", "max_savings", "fastest"]

@dataclass(frozen=True)
class LabelledPlan:
    label: PlanLabel
    plan: Plan
    pending: tuple[PendingOrder, ...]
    effective_cost: Paise                 # SavingsPlan.effective_cost for max_savings; plan.result.total_net otherwise
    savings_vs_baseline: Paise            # baseline.total_net - effective_cost (may be negative for fastest)
    reasons: tuple[Reason, ...]

@dataclass(frozen=True)
class PlanSet:
    baseline: Plan
    plans: tuple[LabelledPlan, ...]       # order: cheapest_now, max_savings, fastest; duplicates removed

def plan(needs, offers, memberships, fillers: Sequence[Filler] = (), schedules=SAMPLE_SCHEDULES,
         settings: PlanSettings = PlanSettings(), pending_settings: PendingSettings = PendingSettings()) -> PlanSet
```
- `cheapest_now` = `plan_cheapest_now`. `max_savings` = `plan_max_savings`, **included only if it has a pending order**.
- `fastest` = `plan_cheapest_now` on needs where each line keeps only the candidates with its minimum `eta_minutes`.
  Leave it out if its orders equal cheapest_now's orders.
- Dedup: a later plan is dropped if its `plan.orders` equals an earlier included plan's `plan.orders`.

## Test cases (write first)
Reuse the golden fixtures (Ex 1, Ex 2, Ex 5) by copying them into the new test files. Don't import from other test modules.
1. Ex 1 (A1 uses 2): `plan()` → labels `("cheapest_now",)` only. Cheapest now `savings_vs_baseline == 5000`.
   Reasons include exactly one SPLIT_FOR_SLOT, amazon, amount 5000, text `"Split Amazon into 2 orders to earn ₹50 more in offers."`
2. Ex 2: labels `("cheapest_now", "max_savings")`. max_savings `effective_cost == 90900`, `savings_vs_baseline == 5000`
   (baseline 95900). Reasons: PENDING_SHORT text `"Holding a Amazon basket: ₹156 short of the ₹500 offer threshold."` and
   FILLER_SUGGEST text `"Add vim ({format_inr(19900)}) to complete it."` with filler_id "vim".
   ("a Amazon" is intentional in v1. Don't add grammar logic.)
3. Ex 5: labels include `cheapest_now`. Atta has a MOVED_PLATFORM reason to blinkit, amount 400, text `"atta moved to Blinkit: ₹4 dearer, but the plan costs less overall."`
4. Fastest: lines with candidates at eta 10 (₹300) and eta 1440 (₹250) → fastest picks eta-10 candidates and has negative `savings_vs_baseline`.
   With all candidates at the same eta → no `fastest` label.
5. DEAD_WEIGHT: single amazon line 120000, A1 (flat ₹50 ≥ ₹500) uses 2, line can't be split → reason amount 5000,
   text `"₹700 above the ₹500 threshold earns nothing. Split it to earn another ₹50."`
6. USES_EXHAUSTED: A1 uses 1, Ex 1 lines → the plan has 1 order, so no USES_EXHAUSTED. Construct a case with 2 qualifying
   orders forced by `lock_platform`/`max_orders` and 1 use → exactly one USES_EXHAUSTED reason.
7. Reasons are sorted, deterministic, and every `amount >= 0`.
8. `plan()` on an empty needs list → baseline with no orders, `plans == (cheapest_now with no orders,)`, no reasons.

## Done when
- [ ] All cases pass. The full suite passes 3× in a row. mypy and ruff are clean. Commit on `feat/optimizer-planset` (no push).
- [ ] `handoff` to claude, then `release`.

## Don'ts
No new dependencies. Only the 4 files listed. Don't change text templates. One command per call, foreground only.
