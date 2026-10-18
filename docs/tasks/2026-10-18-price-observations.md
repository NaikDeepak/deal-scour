# Task: real prices — price observations override sample prices (with freshness)

**Assigned to:** agy  **Lead / reviewer:** claude  **Second review:** codex (read-only)
**Branch:** `feat/price-observations` (from `main`, after `feat/baskets` is merged)  **Worktree:** `../deal-scour-wt-agy`

## Goal
Make plans use **real** prices. A household member records the price they see for a listing ("Fortune 5L on Amazon is ₹649 now,
MRP ₹890, member price ₹629, in stock, tomorrow"). The latest observation for a listing replaces the seed's sample price everywhere:
`GET /deals`, `POST /plans`, `POST /lists/{id}/plan`. Every listing shows where its price came from and how fresh it is (ADR-004,
AGENTS.md invariant 6). No scraping. Manual entry only (link paste is the next task).

## Files you may touch (nothing else)
- `backend/app/domain/models.py`: add `PriceObservation`
- `backend/migrations/versions/0003_price_observation.py` (new)
- `backend/app/domain/catalog.py`: add the current-price layer (below). `load_seed()` stays as is.
- `backend/app/api/v1/prices.py` (new)
- `backend/app/api/v1/deals.py`, `backend/app/api/v1/plans.py`, `backend/app/api/v1/baskets.py`: switch from raw seed prices to current prices
- `backend/tests/api/test_prices.py` (new), `backend/tests/domain/test_current_prices.py` (new), and existing tests only where a fixture needs a DB session

## Runtime boundary
Server-side. Times via `app.core.clock.now()`. Money is int paise. No network calls.

## Schema
`price_observation`: `id`, `household_id` FK, `listing_id` str (a seed listing id; unknown → 422), `listed_paise` int > 0,
`mrp_paise` int ≥ listed, `member_price_paise` int|null (≤ listed), `in_stock` bool = true, `eta_minutes` int|null (≥ 0),
`source` `"manual"` (only value for now; leave room for `"link"|"extension"|"fetcher"`), `note` str|null ≤ 120, `observed_at` (clock.now).
Index on (household_id, listing_id, observed_at).

## Current-price layer (`catalog.py`)
```python
@dataclass(frozen=True)
class CurrentListing:            # a SeedListing with the household's latest observation applied
    listing: SeedListing         # listed/mrp/member_discount/eta replaced by the observation's values when one exists
    source: Literal["sample", "manual"]
    observed_at: datetime | None # None for sample
    freshness: Literal["sample", "fresh", "ok", "stale"]
    in_stock: bool

def current_listings(session, household_id, now) -> list[CurrentListing]
```
- `member_discount` = `listed - member_price` when `member_price_paise` is set, else 0 (the observation is what the user saw).
- `eta_minutes`: the observation's if set, else the seed's.
- Freshness by age = now − observed_at: `fresh` < 6 h, `ok` < 48 h, else `stale`. **Quick-commerce platforms** (blinkit, instamart,
  zepto) use 2 h / 12 h. No observation → `"sample"`.
- **Out of stock** (`in_stock = false` on the latest observation) → the listing is excluded from plan candidates (still shown in deals with `in_stock: false`).

## Endpoints
- `POST /api/v1/prices` `{listing_id, listed_paise, mrp_paise, member_price_paise?, in_stock?, eta_minutes?, note?}` → 201 with the observation.
  Validation → 422.
- `GET /api/v1/prices?listing_id=` → that listing's observations for the household, newest first (max 50).
- `GET /deals`: each deal gains `price_source`, `observed_at` (ISO or null), `freshness`, `in_stock`. Prices and best flags use current prices.
- `POST /plans` and `POST /lists/{id}/plan`: candidates and fillers use current prices. Out-of-stock listings are excluded. Each response
  line gains `price_source` and `freshness`. `/plans` gets the household via `current_household_id` and a DB session (that was implicit before).

## Test cases (write first)
1. No observations → deals identical to today (all `price_source "sample"`, `freshness "sample"`).
2. Observe `stp-4` (amazon Fortune 5L) listed 64900, mrp 89000, member 62900 → deals `stp-4` unit_price 62900 (Prime on),
   `price_source "manual"`, `freshness "fresh"`. Exact need `fortune_sunlite_oil_5l` in `/plans` → line_total 62900.
3. Two observations → the latest wins. `GET /prices?listing_id=stp-4` lists both, newest first.
4. Freshness bands with a frozen clock: amazon observation 5 h old → fresh, 7 h → ok, 49 h → stale. Zepto observation 3 h old → ok, 13 h → stale.
5. Out of stock: observe `stp-4` `in_stock: false` → `/plans` for `fortune_sunlite_oil_5l` uses `stp-5` (flipkart). Deals still list `stp-4` with `in_stock false`.
   If every listing of an exact need is out of stock → that line is `unpriced`.
6. Household isolation: an observation by household 2 (inserted directly) doesn't affect household 1's deals or plans.
7. Validation: unknown listing_id, listed 0, mrp < listed, member > listed, negative eta → 422.
8. Plans response lines carry `price_source` / `freshness` matching the deals view.
9. Baskets created from a saved-list plan (existing flow) copy the current price into `basket_line`.
10. Migration 0003 upgrades from 0002 with data intact.

## Done when
- [ ] All cases pass. The full suite passes 3× in a row. mypy and ruff are clean. Commit on `feat/price-observations` (no push). `handoff` + `release`.

## Don'ts
No new dependencies. No network, no scraping. Don't edit `app/main.py` (the lead wires `prices.router`), the optimizer, pricing or the seed.
No inline `python -c`. One command per call, foreground only.
