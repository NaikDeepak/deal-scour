# Basket Optimizer

*The core of DealScour. Status: Design v1 · 2026-10-18*

## 1. The question it answers

> Given **needs** (with quantities, flexibility and need-by dates), **listings** with current prices,
> **memberships**, **offers with remaining uses** and **fee schedules**: which **orders** should I place,
> on which platform, **now vs. later**, to minimise what I really pay?

The headline example: **Amazon ₹50 cashback on orders ≥ ₹500**.
- One ₹1,000 order earns ₹50. Two orders of ₹500+ earn ₹100, as long as you have two uses.
- One ₹1,000 order has ₹500 of **dead weight**, which is spend that could have unlocked another slot.
- When your needs total ₹860, the plan is one ₹510 order now plus one ₹350 **pending basket**, ₹150 short.
  Fill it with things you'd buy anyway within the deadline.

## 2. Cost model

All money is **integer paise**.

For an order `o` on platform `p`:

```
subtotal(o)  = Σ line_price(l)                       # after item-level coupons and member prices
fees(o)      = delivery(p, subtotal, membership)     # e.g. ₹25 if subtotal < free-delivery threshold
             + handling(p) + platform_fee(p)
             + small_cart(p, subtotal)               # e.g. ₹15 if subtotal < ₹99
             + surge(p)                              # optional, user-toggled ("it's raining")
offers(o)    = Σ value(f, subtotal) × multiplier(f)  # order-level offers applied, see §3
net(o)       = subtotal + fees − offers
```

For a plan `P` (a set of orders):

```
cost(P) = Σ net(o)  over placed orders
        + Σ net(o)  over pending orders, with offer value × confidence ρ (default 0.8)
        + delay_penalty(P)                            # need-by violations are hard; "no rush" items cost 0
```

**Baseline** (shown for comparison): each need bought at its cheapest landed price, all lines for a platform in a single order,
with the best single offer applied. This is roughly what a careful human does today. "Savings" is always shown vs the baseline,
and also vs MRP for the ledger.

**Valuation multiplier.** A rupee of cashback is not always a rupee. Per value type: `cash = 1.00`,
`instant_discount = 1.00`, `amazon_pay = 1.00` (configurable; lower it if you rarely use Amazon Pay),
`supercoins = 0.80`, `points = user-set`. Shown in the UI as "₹50 Amazon Pay (valued ₹50)".

## 3. Offer kinds — every combination we model

| # | Kind | Params | Example | How it's modelled |
|---|---|---|---|---|
| 1 | **Flat threshold** | `min_order`, `value` | ₹50 cashback on ≥ ₹500 | binary `a[f,o]`; `subtotal ≥ min·a` |
| 2 | **% with cap** | `rate_bp`, `cap`, `min_order` | 10% up to ₹100, min ₹500 | `v ≤ rate·subtotal`, `v ≤ cap·a`. **Sweet spot = cap ÷ rate** (₹1,000) |
| 3 | **Tiered** | `[(min, value)…]` | ₹75 off ≥ ₹999, ₹150 off ≥ ₹1,499 | one binary per tier, `Σ tiers ≤ 1` |
| 4 | **Bank / payment** | kind 1–3 + `payment_method` | HDFC 10% up to ₹150, min ₹750 | only if the household has that card; separate stack group |
| 5 | **Free delivery threshold** | `min_order`, `fee` | Free above ₹199, else ₹25 | fee binary per order (part of the fee schedule) |
| 6 | **Small-cart fee** | `below`, `fee` | ₹15 if < ₹99 | fee binary per order |
| 7 | **Item coupon** | `listing`, `value` / `rate` | Clip ₹25 coupon on Surf 2L | lowers `line_price`, no order coupling |
| 8 | **Multi-buy** | `listing(s)`, `buy_n`, `pay_m` or `price_for_n` | 2 for ₹549 | integer qty var, price piecewise by qty |
| 9 | **Subscribe & Save** | `rate_bp`, `rate_bp_at_n`, `n` | 5%, or 10% with 5+ subscriptions | treated as item coupon; tier at n lines |
| 10 | **Membership price** | per listing | Pass price ₹25 lower | baked into `line_price` when membership active |
| 11 | **First-order / new account** | kind 1–3 + `uses=1` | ₹100 off first Zepto order | normal offer with `uses_left = 1` |
| 12 | **Category-restricted** | kind 1–3 + `eligible_categories` | ₹50 on ≥ ₹500 *grocery* | threshold counts only eligible lines |
| 13 | **Brand-funded** | kind 1–3 + `eligible_brands` | ₹40 off on ₹299 of Tata products | as 12 |
| 14 | **Time-window** | `valid_from/to`, `days/hours` | Weekend only | filters which order dates can use it; pending deadlines respect it |

**Stacking.** Each offer has a `stack_group`. At most one offer per group applies to an order. Typical groups:
`platform_coupon`, `bank`, `membership` (always stackable), `item` (always stackable). The user can override this per offer.

**Usage limits.** `uses_left` is per **platform account** and period (per order / per day / per month / lifetime).
`Σ_o a[f,o] ≤ uses_left(f)`.

**Threshold base.** Some offers count MRP and some count price after item coupons. The default is *price after item coupons,
before order offers*, and it's configurable per offer (`threshold_on: "subtotal" | "mrp" | "eligible_subtotal"`).

## 4. Formal model (CP-SAT)

Solved with Google OR-Tools CP-SAT (ADR-006). Integer paise keep every coefficient integral.

**Sets**
- `L`: need lines. `C_l`: candidate listings for line `l` (brand/pack flexibility expands this; urgency filters it).
- `O`: order slots. For each platform `p`, slots `k = 1..K_p`, with `K_p = min(max_uses_on_p + 1, ⌈Σ max price / min_threshold⌉ + 1, 6)`.
- `F_p`: offers usable on platform `p` by an account the household can order from.

**Variables**
- `x[l,c,o] ∈ {0,1}`: line `l` bought as listing `c` in order `o` (only `c` on `o`'s platform).
- `q[l,c,o] ∈ ℕ`: quantity (normally fixed to the need qty; free for multi-buy and pack substitution).
- `u[o] ∈ {0,1}`: order used. `pend[o] ∈ {0,1}`: order is pending (only allowed in the *Max savings* plan).
- `a[f,o] ∈ {0,1}`: offer `f` (or tier) applied to `o`. `v[f,o] ∈ ℕ`: value for % offers.
- `fd[o] ∈ {0,1}`: free delivery reached. `sc[o] ∈ {0,1}`: small-cart fee charged.
- `gap[o] ∈ ℕ`: planned filler spend for a pending order.

**Constraints**
- Each line is fulfilled exactly once: `Σ_{c,o} x[l,c,o] = 1`.
- `x[l,c,o] ≤ u[o]`, and `subtotal[o] = Σ price(c)·q·x` (linearised: price × fixed qty).
- Need-by: if `eta(c) > need_by(l)` then `x[l,c,·] = 0`. If `l` is urgent, `pend[o] = 1 ⇒ x[l,·,o] = 0`.
- Threshold offers: `subtotal[o] + gap[o] ≥ min(f)·a[f,o]`. `gap[o] ≤ G_max·pend[o]`.
  Here `G_max` is the maximum filler spend the user accepts (default ₹250). It is also capped by the **filler pool value** available for that platform.
- `Σ_o a[f,o] ≤ uses_left(f)`. For each stack group and order, at most one `a`.
- % offers: `10000·v[f,o] ≤ rate_bp·(subtotal[o]+gap[o])`, `v[f,o] ≤ cap(f)·a[f,o]`.
- Free delivery: `subtotal[o] ≥ fdt(p)·fd[o]`. Fee charged `= fee(p)·(u[o] − fd[o])` (zero if membership waives it).
- Symmetry breaking: `subtotal[p,k] ≥ subtotal[p,k+1]` and `u[p,k] ≥ u[p,k+1]`.

**Objective** (minimise, lexicographic via weights)

1. `Σ (subtotal + fees) − Σ multiplier·value·(1 − (1−ρ)·pend)`: net money.
2. `+ ε₁ · Σ u[o]`: fewer orders (each order is effort, packaging and a delivery slot).
3. `+ ε₂ · Σ gap[o]`: smaller filler requirements.
4. `+ ε₃ · Σ eta`: faster when otherwise equal.

Note that `gap` adds money to `subtotal + gap` for threshold purposes but **not** to cost. Fillers are things
you'd buy anyway, so their cost belongs to their own future need, not to this plan. ρ discounts the offer for
the risk that the pending basket never completes.

**Solver budget:** 1.0 s wall time, 8 workers. Return the best solution found, and report `OPTIMAL` vs `FEASIBLE` in the plan.

## 5. Heuristic fallback

This runs when CP-SAT times out without a solution, isn't installed, or when instant preview is needed. It is deterministic.

1. **Assign:** each line goes to the listing with the lowest landed unit cost that meets need-by. Lines with `lock` keep their platform.
2. **Group** lines by platform.
3. **Pack per platform** (bin covering): sort lines by price, descending. Open bins up to `uses_left` of the platform's best threshold offer.
   Put each line in the bin with the **smallest remaining shortfall it still fits in**, i.e. best-fit toward the threshold rather than past it.
   Once all bins are covered, spread the rest into the bin that keeps % offers closest to their sweet spot.
4. **Leftover bin below threshold.** If shortfall ≤ `min(G_max, filler_pool)`, mark it **pending**. Otherwise merge it into the bin
   where it costs least, or **re-home** its lines to the next-cheapest platform if that's cheaper all-in.
5. **Fees pass:** for orders below free delivery, try moving one or two lines in from other platforms when the price penalty is less than the fee saved.
6. **Local search** (≤ 300 iterations, first-improvement): *move* line → other order, *swap* two lines, *merge* two orders, *split* order.
   Accept a change if `cost` decreases.
7. Produce the three plans by running with different settings: `pending allowed = false` (Cheapest now), `= true` (Max savings),
   and `ETA weight high` (Fastest).

Cross-check: for instances ≤ 10 lines, CP-SAT and the heuristic must agree within ₹1 on *Cheapest now*. This is a test.

## 6. Worked examples (golden tests)

Prime and Swiggy One are ON, so free delivery applies on Amazon. Prices are net of membership. **All offer terms are illustrative.**

### Ex 1. Split to double the cashback
Offer A1: ₹50 Amazon Pay cashback on ≥ ₹500, **2 uses left**.
Needs on Amazon: Fortune Oil 5L ₹665, Surf Excel 2L ₹344, Tata Toor Dal 2 kg ₹330. Total ₹1,339.

| Plan | Orders | Offer | Net |
|---|---|---|---|
| Baseline (one order) | ₹1,339 | −₹50 | **₹1,289** |
| Optimal | {Oil} ₹665 · {Surf, Dal} ₹674 | −₹50 −₹50 | **₹1,239** |

Saves ₹50. Explanation: *"Split into 2 orders over ₹500 to use both ₹50 cashbacks."*

### Ex 2. Shortfall → pending basket with filler
Same offer, 2 uses. Needs: Oil ₹665, Surf ₹344 (no rush, need-by in 10 days). Restock pool: Vim Gel 750 ml ₹199, due in 8 days.

| Plan | Orders | Offer | Net now | Effective cost of Oil + Surf |
|---|---|---|---|---|
| Cheapest now | {Oil, Surf} ₹1,009 | −₹50 | ₹959 | ₹959 |
| Max savings | {Oil} ₹665 now + **pending** {Surf} ₹344, short ₹156 → filler Vim ₹199 → ₹543 | −₹50 −₹50 | ₹615 now, ₹493 later | **₹909** (₹1,108 paid − ₹199 Vim you needed anyway) |

Saves ₹50. Costs: Surf arrives up to 10 days later, and Vim is bought 8 days early.
UI: *"Hold Surf in a pending Amazon basket (₹156 short). Add Vim Gel (due for restock) to unlock another ₹50. Deadline: 28 Oct."*

### Ex 3. % with cap → sweet spot
Offer B1: HDFC 10% up to ₹100, min ₹500, **2 uses left**. Flipkart needs total ₹1,800.
- One order: min(₹180, ₹100) = ₹100 off → **₹1,700**.
- Two orders (₹1,000 + ₹800): ₹100 + ₹80 → **₹1,620**. Saves ₹80.
- Dead-weight hint for the single order: *"₹800 beyond the ₹1,000 sweet spot earns nothing."*

### Ex 4. Tiered offer, don't split
Offer C1 (1 use): ₹75 off ≥ ₹999, ₹150 off ≥ ₹1,499. Needs ₹1,520.
- One order → ₹150 off → **₹1,370**. Splitting gives at most ₹75. The optimizer keeps one order.
  Splitting is not always better, and the model decides.

### Ex 5. Quick commerce: urgent item pulls fillers
Needs: Milk 1L ₹68 (**urgent**, need today), Bread ₹50 (today), Atta 5 kg ₹289 (no rush). Blinkit, no Zomato Gold: free delivery ≥ ₹199, else ₹25.
Atta is ₹4 cheaper on Instamart, which also needs a ₹199 basket for free delivery.
- Milk + Bread on Blinkit alone: ₹118 + ₹25 fee = ₹143. Atta separately on Instamart (₹285, free delivery) → total ₹428.
- Optimal: Milk + Bread + Atta on Blinkit: ₹407, free delivery → **₹407**. Saves ₹21.
  *"Atta moved to Blinkit: ₹4 dearer, but it saves the ₹25 delivery fee on your urgent order."*

### Ex 6. Uses exhausted → no split
Offer A1 with **1 use left**. Needs ₹1,339 as in Ex 1. Optimal is a single order: ₹1,289. There's no reason to split
(the symmetry is broken toward fewer orders).

### Ex 7. Category-restricted threshold
Offer D1: ₹50 on ≥ ₹500 of *grocery* on Amazon. Needs: Almonds ₹619 (dry fruits, eligible), Phone case ₹299 (not eligible).
The threshold is counted on ₹619 only. If the user had only ₹400 of groceries plus the ₹299 case, the order would *not* qualify.
The UI must say so explicitly.

## 7. Pending basket lifecycle

See `FLOW.md` §4 for the state diagram. The optimizer's part:

- **Deadline** = min(offer `valid_to`, earliest `need_by` among its lines, user-set date).
- **Filler pool** for a platform is the union of:
  1. Restock items due within `deadline + 7 days`.
  2. Wishlist watches whose current price is within 5% of target.
  3. Non-urgent needs on *other* lists, where moving them here costs ≤ ₹10 more than their best platform.
- **Regret-free score** (higher is better), with weights in config:
  `+3` already on a list · `+2` restock due · `+2` non-perishable · `+1` wishlist near target ·
  `−overshoot/₹50` · `−1` per ₹100 of extra pre-purchase · `−3` perishable with shelf life < deadline gap.
- Fillers are **suggested, never auto-added**.
- On every price or offer change, re-check pending baskets. If a basket can be completed more cheaply on another platform now,
  suggest **re-homing** it.

## 8. Explanations

Every decision the optimizer makes produces a `Reason` with a code, the rupee impact and the affected lines. Templates live in `optimizer/explain.py`:

| Code | Template |
|---|---|
| `SPLIT_FOR_SLOT` | Split into {n} orders over ₹{min} to use {n} × ₹{value} cashback. |
| `DEAD_WEIGHT` | ₹{excess} above the ₹{min} threshold earns nothing. {hint} |
| `MOVED_FOR_FEE` | {item} moved to {platform}: ₹{delta} dearer, but it saves ₹{fee} delivery. |
| `PENDING_SHORT` | Holding {platform} basket: ₹{short} short of ₹{value} {offer}. Deadline {date}. |
| `FILLER_SUGGEST` | Add {item} (₹{price}, {why}) to complete it. |
| `TIER_KEEP_TOGETHER` | Kept as one order to reach the ₹{tier_min} tier (₹{tier_value} off). |
| `USES_EXHAUSTED` | Only {n} use(s) of {offer} left, so no point splitting further. |
| `STALE_PRICE` | Price for {item} is {age} old. Check it before ordering. |

## 9. Inputs & outputs (contract)

```python
class PlanRequest(BaseModel):
    needs: list[NeedLine]              # line_id, candidates[ListingQuote], qty, need_by, urgent, lock_platform
    offers: list[OfferInstance]        # kind, params, uses_left, stack_group, multiplier, valid window, account_id
    fee_schedules: dict[Platform, FeeSchedule]
    memberships: dict[Platform, bool]
    filler_pool: list[FillerCandidate] # listing quote + regret score
    settings: PlanSettings             # G_max, rho, max_orders_per_platform, time_budget_ms, today

class PlanSet(BaseModel):
    baseline: Plan
    plans: list[Plan]                  # labelled: cheapest_now | max_savings | fastest (deduplicated)

class Plan(BaseModel):
    label: str
    orders: list[PlannedOrder]         # platform, lines, subtotal, fees[], offers_applied[], net, status: now|pending, shortfall, deadline
    total_net_paise: int
    savings_vs_baseline_paise: int
    reasons: list[Reason]
    solver: Literal["cp_sat_optimal", "cp_sat_feasible", "heuristic"]
```

## 10. Edge cases checklist
- A need has no candidates → shown as "unpriced" and excluded, never silently dropped.
- Out of stock on its best platform → next-best candidate, with reason shown.
- Max quantity per order (e.g. 2 units of a sale item) → `q ≤ max_qty`, and more units spill to another order.
- Same offer on two platform accounts (my Amazon + spouse's Amazon) → two independent offer instances. The plan says which account to use.
- Prices that change between plan and checkout → "Re-check" button re-plans with locked orders.
- A cashback that never arrives → ledger marks it *missed*, and the next plan's ρ for that offer source drops.
- Rounding: platforms round to ₹1. Compute in paise, display rounded rupees, and never let a display round flip a threshold
  (₹499.60 is **not** ≥ ₹500).
