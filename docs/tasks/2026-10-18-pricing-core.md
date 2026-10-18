# Task: pricing core (money, units, fees, item price)

**Assigned to:** agy  **Lead / reviewer:** claude  **Second review:** codex (read-only)
**Branch:** `feat/pricing-core`  **Worktree:** `../deal-scour-wt-agy`

## Goal
Add the pure, tested pricing building blocks every later feature depends on: integer-paise money, pack-size
parsing and unit rates, **order-level** fee schedules, and item (line) prices with membership prices and coupons.
This fixes prototype defects D4, D9 and D15 (`docs/CODE_ANALYSIS.md` §4).

Read first: `AGENTS.md` §4 (invariants 1 and 2), `docs/DECISIONS.md` ADR-009 and ADR-011.

## Files you may touch (nothing else)
- `backend/app/core/money.py` (new)
- `backend/app/pricing/units.py` (new)
- `backend/app/pricing/fee_schedules.py` (new)
- `backend/app/pricing/landed.py` (new)
- `backend/tests/core/test_money.py` (new)
- `backend/tests/pricing/test_units.py` (new)
- `backend/tests/pricing/test_fee_schedules.py` (new)
- `backend/tests/pricing/test_landed.py` (new)

The `__init__.py` files already exist. Don't touch them.

## Runtime boundary
Server-side Python 3.11 only. **Pure functions and frozen dataclasses, standard library only.** No I/O, no clock,
no env/config reads, no new dependencies. Every money value is `int` paise (₹1 = 100). Passing a `float` where
money is expected must raise `TypeError`. Code must pass `mypy --strict` (configured for `app.core` and `app.pricing`)
and `ruff check`.

## API to implement (exact names and signatures)

### `app/core/money.py`
```python
Paise = int

def rupees(amount: str | int) -> Paise
    # "289" -> 28900, "289.5" -> 28950, "289.50" -> 28950, 289 -> 28900, "1,250" -> 125000
    # float -> TypeError; more than 2 decimals, empty, or non-numeric -> ValueError; negative allowed ("-50" -> -5000)
def format_inr(paise: Paise) -> str
    # Indian digit grouping. Paise shown only when non-zero.
    # 125000 -> "₹1,250"; 12500000 -> "₹1,25,000"; 28950 -> "₹289.50"; 0 -> "₹0"; -5000 -> "-₹50"
    # float -> TypeError
def pct_of(paise: Paise, rate_bp: int) -> Paise
    # basis points (1000 bp = 10%), result FLOORED toward zero: pct_of(180000, 1000) == 18000; pct_of(999, 1000) == 99
    # rate_bp < 0 -> ValueError; float -> TypeError
```

### `app/pricing/units.py`
```python
Unit = Literal["g", "ml", "pc"]

@dataclass(frozen=True)
class Pack:
    qty: int          # in grams, millilitres or pieces
    unit: Unit

def parse_pack(label: str) -> Pack
    # case-insensitive, optional spaces: "5kg","5 Kg","500g","500 gm","1.5kg","1L","1 l","1 ltr","1 litre","750ml",
    # "2 x 500g" / "2x500g" (multiplier), "6 pcs","6 pc","pack of 6" -> pieces
    # unparseable, zero or negative -> ValueError
def default_basis(unit: Unit) -> tuple[int, str]
    # g -> (1000, "kg"), ml -> (1000, "L"), pc -> (1, "pc")
def unit_rate(price: Paise, pack: Pack, basis_qty: int | None = None) -> Paise
    # paise per basis_qty of pack.unit (default from default_basis), rounded HALF UP to whole paise
    # pack.qty <= 0 or basis_qty <= 0 -> ValueError
```

### `app/pricing/fee_schedules.py`
```python
Platform = Literal["amazon", "flipkart", "blinkit", "instamart", "zepto"]

@dataclass(frozen=True)
class FeeSchedule:
    platform: Platform
    delivery_fee: Paise
    free_delivery_min: Paise | None           # non-members: free when subtotal >= this; None = never free
    member_free_delivery_min: Paise | None    # members: free when subtotal >= this; None = use free_delivery_min
    handling_fee: Paise = 0
    platform_fee: Paise = 0
    small_cart_below: Paise | None = None     # small-cart fee charged when subtotal < this
    small_cart_fee: Paise = 0

@dataclass(frozen=True)
class FeeBreakdown:
    delivery: Paise
    handling: Paise
    platform: Paise
    small_cart: Paise
    surge: Paise
    @property
    def total(self) -> Paise: ...

def order_fees(schedule: FeeSchedule, subtotal: Paise, is_member: bool, surge: Paise = 0) -> FeeBreakdown
    # subtotal < 0 or surge < 0 -> ValueError
    # subtotal == 0 -> all zero (no order is placed)
    # thresholds compare in paise with >= (49_960 is NOT >= 50_000)

SAMPLE_SCHEDULES: dict[Platform, FeeSchedule]   # sample values, user-editable later; EXACTLY:
    # amazon:    delivery 4000, free_delivery_min 49900, member_free_delivery_min 0
    # flipkart:  delivery 4000, free_delivery_min 49900, member_free_delivery_min 0
    # instamart: delivery 2500, free_delivery_min 49900, member_free_delivery_min 19900, small_cart_below 9900, small_cart_fee 1500
    # blinkit:   delivery 2500, free_delivery_min 19900, member_free_delivery_min 0,     small_cart_below 9900, small_cart_fee 1500
    # zepto:     delivery 2500, free_delivery_min 19900, member_free_delivery_min 0,     small_cart_below 9900, small_cart_fee 1500
```

### `app/pricing/landed.py`
```python
@dataclass(frozen=True)
class ItemPrice:
    listed: Paise
    mrp: Paise
    member_price: Paise | None = None   # used only when is_member
    item_coupon: Paise = 0              # off each unit

def unit_price(p: ItemPrice, is_member: bool) -> Paise
    # (member_price if is_member and member_price is not None else listed) - item_coupon, floored at 0
def line_price(p: ItemPrice, qty: int, is_member: bool) -> Paise
    # unit_price * qty; qty < 1 -> ValueError. NO delivery or order fees here (ADR-011).
def discount_bp(p: ItemPrice, is_member: bool) -> int
    # discount vs MRP on the unit price only, in basis points, floored; mrp <= 0 -> 0; never negative
```

## Test cases (write these first, make them fail, then implement)

**money**
1. `rupees("289") == 28900`, `rupees("289.5") == 28950`, `rupees("289.50") == 28950`, `rupees(289) == 28900`, `rupees("1,250") == 125000`, `rupees("-50") == -5000`.
2. `rupees(289.5)` raises `TypeError`. `rupees("1.234")`, `rupees("")`, `rupees("abc")` raise `ValueError`.
3. `format_inr`: 125000 → `"₹1,250"`, 12500000 → `"₹1,25,000"`, 1234567800 → `"₹1,23,45,678"`, 28950 → `"₹289.50"`, 5 → `"₹0.05"`, 0 → `"₹0"`, -5000 → `"-₹50"`. A float raises `TypeError`.
4. `pct_of(180000, 1000) == 18000`, `pct_of(999, 1000) == 99`, `pct_of(100000, 0) == 0`. `pct_of(100, -1)` raises `ValueError`.

**units**
5. `parse_pack`: "5kg" → (5000, g), "5 Kg" → (5000, g), "500 gm" → (500, g), "1.5kg" → (1500, g), "1L" / "1 ltr" / "1 litre" → (1000, ml), "750ml" → (750, ml), "2 x 500g" and "2x500g" → (1000, g), "6 pcs" and "pack of 6" → (6, pc).
6. `parse_pack("")`, `parse_pack("big")`, `parse_pack("0kg")` raise `ValueError`.
7. `unit_rate(28900, Pack(5000,"g")) == 5780` (₹57.80/kg). `unit_rate(61900, Pack(1000,"g"), 100) == 6190` (₹61.90/100g). `unit_rate(66500, Pack(5000,"ml")) == 13300`.
8. Half-up rounding: `unit_rate(1001, Pack(2000,"g")) == 501` (500.5 → 501). `unit_rate(100, Pack(3,"pc")) == 33`.
9. `default_basis("g") == (1000, "kg")`, `default_basis("ml") == (1000, "L")`, `default_basis("pc") == (1, "pc")`.

**fees**
10. Amazon, Prime member, subtotal ₹100 → delivery 0, total 0.
11. Amazon, non-member: subtotal ₹498 (49800) → delivery 4000. Subtotal ₹499 (49900) → delivery 0.
12. Instamart, member: 19899 → delivery 2500. 19900 → 0. Non-member at 19900 → 2500 (non-member threshold is 49900).
13. Blinkit, non-member, subtotal 9800 → delivery 2500 + small_cart 1500 = total 4000. Subtotal 9900 → small_cart 0.
14. **Regression D4 (one fee per order):** five Instamart non-member items of ₹50 each → one order, subtotal 25000 → total fees 2500 (not 5 × 2500).
15. `order_fees(..., subtotal=0, ...)` → total 0 even for a non-member on Blinkit.
16. Surge is added: Blinkit member, 30000, surge 2000 → total 2000. A negative subtotal or negative surge raises `ValueError`.
17. `SAMPLE_SCHEDULES` has exactly the 5 platforms and the exact values listed above (one assertion per platform).
18. `FeeSchedule` is frozen: assigning to `.delivery_fee` raises `dataclasses.FrozenInstanceError`.

**landed**
19. `ItemPrice(listed=29200, mrp=36500, member_price=27700)`: member → `unit_price` 27700. Non-member → 29200.
20. `member_price=None`, member → falls back to `listed`.
21. `item_coupon=2500` on listed 36900, non-member → 34400. Coupon larger than the price → 0, never negative.
22. `line_price(p, 3, False) == 3 * unit_price(p, False)`. `line_price(p, 0, False)` raises `ValueError`.
23. **Regression D15:** `discount_bp(ItemPrice(listed=29200, mrp=36500), False) == 2000` (20.00%). No delivery fee is involved, so the value is the same as for a member without a member price.
24. `discount_bp` with mrp 0 → 0. Listed above MRP → 0, never negative.

## Seams
None. Nothing is wired into the API in this task.

## Done when
- [ ] All 24 cases pass. The full suite `cd backend && .venv/bin/pytest` passes 3 runs in a row.
- [ ] `.venv/bin/ruff check .` and `.venv/bin/mypy` are clean (run from `backend/`).
- [ ] Commit on `feat/pricing-core` (no push).
- [ ] `scripts/collab.sh handoff agy claude "feat/pricing-core · <done> · <test result> · <anything unsure>"`
- [ ] `scripts/collab.sh release agy`

## Don'ts
- No new dependencies. No changes outside the file list. No background commands. One command per call.
- No floats in any money path (`Decimal` is fine *inside* `rupees()` for parsing).
- The venv lives in the main checkout. In your worktree, run tests with
  `/Users/deepaknaik/Downloads/1. AI Live/deal-scour/backend/.venv/bin/pytest` from `backend/`, or create a local
  `.venv` in the worktree's `backend/` using the same `pip install -e '.[dev]'` command. Either is fine.
