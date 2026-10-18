# Task: `POST /api/v1/plans` — plan a shopping list against the catalog

**Assigned to:** agy  **Lead / reviewer:** claude  **Second review:** codex (read-only)
**Branch:** `feat/plans-endpoint` (from `main`, after `feat/optimizer-planset` is merged)  **Worktree:** `../deal-scour-wt-agy`

## Goal
The first end-to-end planning call. Send a list of needs (by catalog product), memberships, offers and optional fillers, and get
back the PlanSet (baseline + Cheapest now / Max savings / Fastest) as JSON, with every money field in paise and reasons as text.
There's no database yet: the catalog is the seed (`app.domain.catalog.load_seed`), and offers come in the request body.

## Files you may touch (nothing else)
- `backend/app/api/v1/plans.py` (new): router, request/response Pydantic models, mapping to and from the optimizer
- `backend/tests/api/test_plans.py` (new)

Use, but do not modify: `app/optimizer/*`, `app/domain/catalog.py`, `app/pricing/*`, `app/api/v1/deals.py`. **Do not edit `app/main.py`.**
Tests mount the router on their own `FastAPI()` with prefix `/api/v1`.

## Runtime boundary
Server-side. Request → build `NeedLine`s / `Offer`s / `Filler`s → `optimizer.planset.plan(...)` → response. All optimizer
math stays in `app/optimizer`. This module only maps data (ADR-019). Any `ValueError` raised while building optimizer inputs → **422**
with the message in `detail`.

## Request (Pydantic v2)
```jsonc
{
  "members": ["amazon", "instamart", "flipkart"],      // default: this list; unknown platform -> 422
  "needs": [
    {"line_id": "atta", "product_key": "aashirvaad_atta", "qty": 1,
     "need_by_minutes": null, "lock_platform": null}   // unknown product_key -> 422; duplicate line_id -> 422; qty >= 1
  ],
  "offers": [
    {"id": "A1", "platform": "amazon", "kind": "flat", "min_order_paise": 50000, "value_paise": 5000,
     "rate_bp": 0, "cap_paise": null, "tiers": [],        // tiers: [[min_paise, value_paise], ...]
     "uses_left": 2, "stack_group": "platform_coupon", "value_type": "amazon_pay",
     "multiplier_bp": null, "eligible_categories": null}
  ],
  "fillers": [{"filler_id": "vim", "listing_id": "cln-3", "score": 5}],   // unknown listing_id -> 422
  "max_filler_gap_paise": 25000, "rho_bp": 8000                          // optional PendingSettings overrides
}
```
Mapping:
- Candidates for a need = **every seed listing with that product_key**. `Candidate(listing_id=id, platform,
  unit_price=pricing.landed.unit_price(listing.item_price(), is_member), eta_minutes)`. `NeedLine.category` = the listing's category.
- Filler = `Filler(filler_id, listing_id, platform, category, unit_price (membership-adjusted), score)` from the seed listing.
- `memberships` = `{p: p in members}` for all 5 platforms.

## Response
```jsonc
{
  "baseline": PlanOut,
  "plans": [ {"label": "cheapest_now" | "max_savings" | "fastest", ...PlanOut,
              "effective_cost_paise": int, "savings_vs_baseline_paise": int,
              "reasons": [{"code": str, "platform": str, "amount_paise": int, "line_ids": [str], "text": str}]} ],
}
// PlanOut:
{ "orders": [ { "platform": str, "status": "now" | "pending",
                "lines": [{"line_id": str, "listing_id": str, "title": str, "pack_label": str, "unit_price_paise": int,
                           "qty": int, "is_filler": bool}],
                "subtotal_paise": int,
                "fees": {"delivery": int, "handling": int, "platform": int, "small_cart": int, "surge": int, "total": int},
                "offers_applied": [{"offer_id": str, "face_value_paise": int, "effective_value_paise": int}],
                "net_paise": int,
                "shortfall_paise": int | null, "target_offer_id": str | null } ],
  "total_subtotal_paise": int, "total_fees_paise": int, "total_offer_value_paise": int, "total_net_paise": int,
  "unpriced": [str] }
```
`status` is `"pending"` only for the order at a `PendingOrder.order_index`. `is_filler` is true for lines whose line_id is a filler_id.
`title` and `pack_label` come from the seed listing (for fillers too).

## Test cases (write first)
1. Minimal: needs [atta] (aashirvaad_atta), default members, no offers → 200. Cheapest now has 1 order on **instamart** with
   `unit_price_paise == 27700`, `fees.total == 0` (Swiggy One member and 27700 ≥ the member free-delivery minimum of 19900),
   `net_paise == 27700`. Baseline is equal. One plan (`cheapest_now`). `savings_vs_baseline_paise == 0`.
2. `members=["blinkit"]` → atta on blinkit at 27700, delivery 0 (Gold member).
3. Consistency: for the request in case 5, every number in the response equals what `optimizer.planset.plan(...)` returns
   when you call it directly with the same mapped inputs (`total_net`, each order's `net`, `effective_cost`, reasons text).
4. Unknown `product_key` → 422. Duplicate `line_id` → 422. Unknown member platform → 422. `qty: 0` → 422. Unknown filler
   `listing_id` → 422. An offer with `kind: "flat"` and `value_paise: 0` → 422 (ValueError mapped).
5. **Monthly basket with a split** (seed data, default members): needs oil (`fortune_oil`), surf (`surf_liquid`),
   almonds (`california_almonds`), ghee (`amul_ghee`). Offer A1 amazon flat 5000 ≥ 50000, uses 2.
   Assert: 200. Every need is in exactly one order of `cheapest_now`. `cheapest_now.total_net_paise <= baseline.total_net_paise`.
   Reasons are a list of objects with non-empty `text`.
6. Pending through the API: needs surf (`surf_liquid`) only, `lock_platform: "amazon"`. A1 uses 2. Fillers: one amazon listing
   from the seed whose price closes the gap (pick it in the test by scanning `load_seed()`). Assert that if `max_savings` is present,
   it has exactly one order with `status: "pending"`, a positive `shortfall_paise`, and `target_offer_id == "A1"`, and that its
   filler lines have `is_filler: true`. (If no seed listing closes the gap under `max_filler_gap_paise`, raise the gap in the request.)
7. `need_by_minutes: 30` on a product with no listing that fast → that line is in `unpriced` for every plan.
8. Response money fields are all `int` (walk the JSON and assert no float anywhere).

## Seams
The last line of `plans.py` must be: `# HOOK: app.include_router(plans.router, prefix="/api/v1") in app/main.py (wired by lead)`

## Done when
- [ ] All cases pass. The full suite passes 3× in a row. mypy and ruff are clean. Commit on `feat/plans-endpoint` (no push).
- [ ] `handoff` to claude, then `release`.

## Don'ts
No new dependencies. Only the 2 files. No database. No optimizer logic in the API module. One command per call, foreground only.
