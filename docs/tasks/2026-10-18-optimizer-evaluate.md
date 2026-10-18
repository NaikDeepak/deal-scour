# Task: optimizer — offers and plan evaluation

**Assigned to:** agy  **Lead / reviewer:** claude  **Second review:** codex (read-only)
**Branch:** `feat/optimizer-evaluate` (from `main`)  **Worktree:** `../deal-scour-wt-agy`

## Goal
Given a **fixed** split of lines into orders, compute exactly what the user pays: subtotal, order-level fees, which offers
apply to which order (**optimally**, respecting uses left and stacking), and net. Both the heuristic and the CP-SAT solver
(later tasks) will be scored by this function, and the worked examples in `docs/BASKET_OPTIMIZER.md` §6 become tests.

Read first: `docs/BASKET_OPTIMIZER.md` §2, §3 (kinds 1–4, 12, stacking, usage limits) and §6. `AGENTS.md` §4 invariants 1–3.

## Files you may touch (nothing else)
- `backend/app/optimizer/contract.py` (new)
- `backend/app/optimizer/offers.py` (new)
- `backend/app/optimizer/evaluate.py` (new)
- `backend/tests/optimizer/test_offers.py` (new)
- `backend/tests/optimizer/test_evaluate.py` (new)

Use, but do not modify: `app/core/money.py` (`Paise`, `pct_of`), `app/pricing/fee_schedules.py` (`Platform`, `FeeSchedule`,
`FeeBreakdown`, `order_fees`, `SAMPLE_SCHEDULES`).

## Runtime boundary
Pure Python, standard library only. No I/O, no clock, no globals that change. Frozen dataclasses. Integer paise everywhere.
It must pass `mypy --strict` (already configured for `app.optimizer`) and `ruff`.

## API to implement

### `app/optimizer/contract.py`
```python
OfferKind = Literal["flat", "pct_cap", "tiered"]
ValueType = Literal["cash", "instant", "amazon_pay", "supercoins"]
DEFAULT_MULTIPLIER_BP: dict[ValueType, int] = {"cash": 10000, "instant": 10000, "amazon_pay": 10000, "supercoins": 8000}

@dataclass(frozen=True)
class Offer:
    id: str
    platform: Platform
    kind: OfferKind
    min_order: Paise = 0                         # flat, pct_cap (tiered uses tiers)
    value: Paise = 0                             # flat
    rate_bp: int = 0                             # pct_cap
    cap: Paise | None = None                     # pct_cap; None = uncapped
    tiers: tuple[tuple[Paise, Paise], ...] = ()  # tiered: ((min_order, value), ...)
    uses_left: int = 1
    stack_group: str = "platform_coupon"
    value_type: ValueType = "cash"
    multiplier_bp: int | None = None             # None -> DEFAULT_MULTIPLIER_BP[value_type]
    eligible_categories: frozenset[str] | None = None   # None = every category counts toward the threshold
    # __post_init__ raises ValueError when:
    #   flat: value <= 0 | pct_cap: rate_bp <= 0 or rate_bp > 10000 or (cap is not None and cap <= 0)
    #   tiered: tiers empty, or mins not strictly increasing, or values not strictly increasing, or any value <= 0
    #   any kind: min_order < 0, uses_left < 0, multiplier_bp is not None and not 0..10000

@dataclass(frozen=True)
class OrderLine:
    line_id: str
    category: str
    unit_price: Paise
    qty: int = 1                                 # qty < 1 -> ValueError
    @property
    def total(self) -> Paise: ...                # unit_price * qty

@dataclass(frozen=True)
class Order:
    platform: Platform
    lines: tuple[OrderLine, ...]                 # empty -> ValueError
    is_member: bool
    surge: Paise = 0
    @property
    def subtotal(self) -> Paise: ...
```

### `app/optimizer/offers.py`
```python
def eligible_subtotal(offer: Offer, order: Order) -> Paise   # sum of lines whose category is eligible
def face_value(offer: Offer, eligible: Paise) -> Paise
    # flat:    value if eligible >= min_order else 0
    # pct_cap: if eligible >= min_order: min(pct_of(eligible, rate_bp), cap) (cap None = no min) else 0
    # tiered:  value of the highest tier whose min <= eligible, else 0
def effective_value(offer: Offer, face: Paise) -> Paise      # face * multiplier // 10000 (floor)
```

### `app/optimizer/evaluate.py`
```python
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
    applied: tuple[AppliedOffer, ...]            # sorted by offer_id
    net: Paise                                    # subtotal + fees.total - sum(effective_value)

@dataclass(frozen=True)
class PlanResult:
    orders: tuple[OrderResult, ...]               # same order as the input
    total_subtotal: Paise
    total_fees: Paise
    total_offer_value: Paise                      # sum of effective values
    total_net: Paise

def evaluate_plan(
    orders: Sequence[Order],
    offers: Sequence[Offer],
    schedules: Mapping[Platform, FeeSchedule] = SAMPLE_SCHEDULES,
) -> PlanResult
```

**Assignment rules (the heart of this task):**
- An offer can apply only to orders on its own `platform`, and only when its `face_value > 0` for that order.
- Each order gets **at most one offer per `stack_group`**. Different groups stack.
- Each offer is used on **at most `uses_left` orders** across the whole plan.
- Choose the assignment that **maximises total effective value**. This is exact, not greedy: a greedy pass can be wrong (see case 14).
  Stack groups are independent, so solve each group separately. Within a group, use a DP over orders with a memo keyed on the
  remaining-uses tuple, or any other exact method.
- Tie-break (deterministic): among assignments with equal total value, prefer **fewer offer uses**. If still tied, compare
  assignments order by order (input order) and prefer the one whose order gets an offer with the smaller id, where
  **"no offer" ranks after every id**. Earlier orders get offers first, and lower ids win (cases 9, 17).
- Performance: 8 orders × 5 offers in one group must evaluate in under 50 ms.

## Test cases (write these first, make them fail, then implement)

Amazon and Flipkart below are **member** orders (no fees) unless stated. Money is in paise.

**offers.py**
1. Flat ₹50 ≥ ₹500: `face_value` at 49999 → 0, at 50000 → 5000.
2. pct_cap 10% cap ₹100 min ₹500: at 49999 → 0. At 80000 → 8000. At 100000 → 10000. At 180000 → 10000 (capped). With `cap=None` at 180000 → 18000.
3. Tiered ((99900, 7500), (149900, 15000)): 99899 → 0, 99900 → 7500, 149899 → 7500, 152000 → 15000.
4. `effective_value`: supercoins face 10000 → 8000. Explicit `multiplier_bp=5000` → 5000. Cash → 10000. Floor: supercoins face 999 → 799.
5. `eligible_subtotal` with `eligible_categories={"dryfruits"}` on lines (dryfruits 61900, electronics 29900) → 61900. With None → 91800.
6. Validation: flat with value 0, pct_cap with rate_bp 0 or 10001, tiered with tiers ((99900, 7500), (99900, 9000)), uses_left -1, and an empty `Order` all raise `ValueError`. `OrderLine` qty 0 raises `ValueError`.

**evaluate_plan: worked examples (BASKET_OPTIMIZER §6)**
Offer A1 = flat ₹50 ≥ ₹500, amazon, `value_type="amazon_pay"`. Lines: Oil 66500, Surf 34400, Dal 33000 (category "staples").
7. Ex 1, A1 `uses_left=2`, one order (Oil, Surf, Dal) → `total_net == 128900`, one applied offer.
8. Ex 1, A1 `uses_left=2`, orders (Oil) + (Surf, Dal) → `total_net == 123900`, `total_offer_value == 10000`.
9. Ex 6, A1 `uses_left=1`, orders (Oil) + (Surf, Dal) → `total_net == 128900`. Exactly one order has the offer: order 0, by the tie-break.
10. Ex 3, flipkart B1 = pct_cap 1000 bp, cap 10000, min 50000, `stack_group="bank"`, `uses_left=2`: one order of a single 180000 line → `total_net == 170000`. Orders 100000 + 80000 → `total_net == 162000`.
11. Ex 4, flipkart C1 tiered ((99900, 7500), (149900, 15000)), `uses_left=1`: one order 152000 → `137000`. Orders 99900 + 52100 → `144500`.
12. Ex 7, amazon D1 flat ₹50 ≥ ₹500 `eligible_categories={"dryfruits"}`: order (dryfruits 61900, electronics 29900) → `86800`. Order (dryfruits 40000, electronics 29900) → no offer, `69900`.
13. Ex 5 fees, blinkit **non-member**: order (6800, 5000) → fees.delivery 2500, `net == 14300`. Order (6800, 5000, 28900) → delivery 0, `net == 40700`.

**evaluate_plan: assignment rules**
14. **Greedy trap.** amazon X = flat 5000 ≥ 30000 (uses 1), Y = flat 4000 ≥ 50000 (uses 1), same group. Orders A = 60000, B = 40000 → A gets Y, B gets X, `total_offer_value == 9000`. A greedy best-per-order pass would give 5000.
15. Stacking: amazon P = flat 5000 ≥ 50000 (group "platform_coupon"), K = pct_cap 1000 bp cap 10000 min 50000 (group "bank"). One order of 100000 → both apply, `net == 85000`, applied sorted by id.
16. Same group, two offers, one order of 100000: P1 flat 5000 ≥ 50000 and P2 flat 7500 ≥ 50000 → only P2 applies, `net == 92500`.
17. Equal-value tie: Q1 and Q2 both flat 5000 ≥ 50000, same group, uses 1, one order → applied offer id is `"Q1"`.
18. Platform mismatch: a flipkart offer is never applied to an amazon order. `uses_left=0` → never applied.
19. Fewer-uses tie-break: R = flat 5000 ≥ 50000, uses 2, `multiplier_bp=0` (worth nothing). Two qualifying orders → no applied offers at all.
20. Totals: for any plan, `total_net == total_subtotal + total_fees - total_offer_value`, and each `OrderResult.net` follows its formula. Check on the plan from case 15 plus a blinkit non-member order.
21. Performance: 8 amazon orders of 50000..120000 and 5 flat offers (uses 1–3) in one group evaluate in < 50 ms (use `time.perf_counter`, allow 3 attempts).

## Seams
None.

## Done when
- [ ] All 21 cases pass. The full suite (`.venv/bin/python -m pytest` from `backend/`) passes 3 runs in a row.
- [ ] `.venv/bin/python -m mypy` and `.venv/bin/python -m ruff check .` are clean.
- [ ] Commit on `feat/optimizer-evaluate` (no push. The lead pushes and opens the PR).
- [ ] `scripts/collab.sh handoff agy claude "feat/optimizer-evaluate · <done> · <test result> · <anything unsure>"`
- [ ] `scripts/collab.sh release agy`

## Don'ts
- No new dependencies (no OR-Tools yet: that's a later task). No edits outside the file list.
- Don't build the heuristic packer or choose order splits. This task only **scores** a given split.
- One command per call, foreground only.
