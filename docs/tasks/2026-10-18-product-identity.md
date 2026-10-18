# Task: exact products + families (fix "5 L oil planned as a 1 L pouch")

**Assigned to:** agy  **Lead / reviewer:** claude  **Second review:** codex (read-only)
**Branch:** `feat/product-identity` (already checked out. The lead's seed commit `3813aa9` is the first commit)  **Worktree:** `../deal-scour-wt-agy`

## Goal
The seed now has `product_key` = **one exact pack** (e.g. `fortune_sunlite_oil_5l`) and a new `family_key` = interchangeable
items (e.g. `sunflower_oil`) (ADR-012). Make the catalog, `GET /deals` and `POST /plans` use them:
- An **exact** need (`product_key`) can only be filled by listings of that exact pack.
- A **flexible** need (`family_key` + `quantity` like `"5L"`) can be filled by any pack in the family. Each candidate is priced as
  `ceil(target / pack) × pack price`, so a 1 L pouch never undercuts a 5 L can just by being smaller.

The current tests reference the old keys and fail on this branch. Updating them is part of this task.

## Files you may touch (nothing else)
- `backend/app/domain/catalog.py`
- `backend/app/api/v1/deals.py`
- `backend/app/api/v1/plans.py`
- `backend/tests/domain/test_catalog.py`, `backend/tests/api/test_deals.py`, `backend/tests/api/test_plans.py`, `backend/tests/test_health.py`

Do **not** modify `app/seed/prototype_catalog.json` (the lead owns the data) or anything in `app/optimizer/` or `app/pricing/`.

## Runtime boundary
Server-side mapping only. The optimizer is unchanged: a flexible need becomes one `NeedLine` with `qty=1` whose candidates carry the
**bundle price** (`unit_price × packs`). The API keeps a `listing_id → packs` map per line to render the response. No new dependencies.

## Changes

### catalog.py
- `SeedListing.family_key: str` (loaded from JSON).

### deals.py
- `DealOut` gains `family_key: str` and `is_best_in_family: bool`: lowest `unit_rate_paise` among all listings with the same
  `family_key` (computed before filters, ties → all true), using the same `rate_basis` per listing.
- `is_best_in_product` stays, but is now per exact `product_key`.
- New optional query param `family` (exact match filter on `family_key`).

### plans.py: request
`NeedIn` becomes:
```jsonc
{ "line_id": str, "product_key": str | null, "family_key": str | null, "quantity": str | null,
  "qty": 1..99, "need_by_minutes": int | null, "lock_platform": Platform | null }
```
- **Exactly one** of `product_key` / `family_key` → else 422.
- Exact need: `quantity` must be null (422 otherwise). Candidates = listings with that `product_key`, `NeedLine.qty = qty` (packs), as today.
- Flexible need: `quantity` required (422 if missing or unparseable by `parse_pack`). `target = parse_pack(quantity).qty × qty`.
  Candidates = family listings whose pack unit equals the quantity's unit. If none match → 422 naming the family. For each candidate:
  `packs = ceil(target / pack.qty)`, `Candidate.unit_price = membership-adjusted unit price × packs`. `NeedLine.qty = 1`.
- Unknown `product_key` or `family_key` → 422.

### plans.py: response
Each line becomes:
```jsonc
{ "line_id", "listing_id", "title", "pack_label", "packs": int, "unit_price_paise": int /* per pack */,
  "line_total_paise": int /* unit_price_paise × packs */, "is_filler": bool }
```
(The old `qty` field is removed.) For exact needs `packs = qty`. For flexible needs `packs` = the computed packs. For fillers `packs = 1`.
`line_total_paise` must equal the PlannedLine's `unit_price × qty`.

## Test cases (update old tests to the new keys, then add these)
1. `load_seed()`: 28 listings, **22** distinct `product_key`s, **15** distinct `family_key`s. Every listing has a non-empty family_key.
2. `GET /deals?family=sunflower_oil` → 3 deals (`stp-4`, `stp-5`, `stp-6`). Only `stp-4` has `is_best_in_family` (13300/L vs 13540, 14200).
   `stp-6` has `is_best_in_product` (the only 1 L listing).
3. Default `GET /deals`: `is_best_in_product` is true for exactly one listing per product_key, except exact ties.
4. **Regression (the bug):** exact need `fortune_sunlite_oil_5l` → cheapest_now line `listing_id == "stp-4"`, `packs == 1`, `line_total_paise == 66500`.
   No plan ever contains `stp-6`.
5. Flexible `sunflower_oil`, `quantity "5L"` → `stp-4`, 66500. With `lock_platform: "zepto"` → `stp-6`, `packs 5`, `unit_price_paise 14200`, `line_total_paise 71000`.
6. Flexible `almonds`, `quantity "1kg"` → `alm-1` (61900). With `need_by_minutes: 30` → `alm-2` (instamart, eta 14), `packs 2`, `line_total_paise 80000`.
7. **Round-up:** flexible `tea`, `quantity "1.5kg"` → `bev-2` (500 g × 3 = 71100) beats `bev-1` (1 kg × 2 = 92000).
8. `qty` multiplies the target: flexible `tea`, `quantity "500g"`, `qty 2` → target 1000 g → `bev-1` (46000) beats `bev-2` × 2 (47400).
9. 422s: both keys set. Neither key set. Flexible without `quantity`. Exact with `quantity`. `quantity "5kg"` for `sunflower_oil` (unit mismatch).
   `quantity "lots"`. Unknown family. The old key `"fortune_oil"` as a product_key.
10. Every response line: `line_total_paise == unit_price_paise * packs`. All money is int. Filler lines have `packs == 1`.
11. Update every old-key test (`aashirvaad_atta` → `aashirvaad_select_atta_5kg`, `fortune_oil` → `fortune_sunlite_oil_5l`,
    `surf_liquid` → `surf_excel_matic_fl_liquid_2l`, `california_almonds` → `happilo_almonds_1kg` or family `almonds`, `amul_ghee` →
    `amul_cow_ghee_1l`, `nutraj_walnuts` → `nutraj_walnuts_500g`) so they keep testing the same behaviour. If a hard-coded number changes
    because a product group is now split, recompute it from the seed and say so in the handoff.

## Done when
- [ ] All cases pass. The full suite passes 3× in a row. mypy and ruff are clean. New commit on `feat/product-identity` (no push).
- [ ] `handoff` to claude (list any test numbers you changed and why), then `release`.

## Don'ts
No new dependencies. Don't touch the seed JSON, the optimizer or pricing. No inline `python -c` scripts (they won't be approved);
explore through tests. One command per call, foreground only.
