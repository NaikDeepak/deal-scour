# Task: add your own products by pasting a link (custom listings)

**Assigned to:** agy  **Lead / reviewer:** claude  **Second review:** codex (read-only)
**Branch:** `feat/custom-listings` (from `main`)  **Worktree:** `../deal-scour-wt-agy`

## Goal
The catalog is limited to 28 sample listings. A household member pastes a product link (Amazon, Flipkart, Blinkit, Zepto or Instamart),
fills in name, brand, pack size, category and family, plus the price they see, and it becomes a **custom listing**. Custom listings
work everywhere seed listings do: `/deals`, list needs (exact or family), `/plans`, baskets, `/prices`. Each one keeps its real product URL.
The next task, the Amazon/Flipkart price fetcher, refreshes listings by that URL.

## Files you may touch (nothing else)
- `backend/app/sources/__init__.py` (exists, empty), `backend/app/sources/urls.py` (new): URL parsing
- `backend/app/domain/models.py`: add `CustomListing`
- `backend/migrations/versions/0005_custom_listing.py` (new)
- `backend/app/domain/catalog.py`: merge custom listings into the catalog layer
- `backend/app/domain/need_rules.py`: validate needs against the household's merged catalog (seed + custom)
- `backend/app/api/v1/listings.py` (new)
- `backend/app/api/v1/plans.py`, `deals.py`, `lists.py`, `baskets.py`, `prices.py`: only to pass the household/session through, so custom listings are included
- `backend/tests/sources/__init__.py`, `backend/tests/sources/test_urls.py`, `backend/tests/api/test_listings.py` (new), `backend/tests/test_migrations.py`

## Runtime boundary
Server-side. **No network calls in this task.** URL parsing is pure string work (`urllib.parse` + regex). Money is int paise. Times via `clock.now()`.

## `sources/urls.py`
```python
@dataclass(frozen=True)
class ProductRef:
    platform: Platform
    sku: str            # amazon ASIN | flipkart pid | blinkit prid | zepto pvid | instamart item id
    url: str            # canonical URL (below)

def parse_product_url(url: str) -> ProductRef   # ValueError with a helpful message otherwise
```
| Platform | Accepted hosts | Path patterns → sku | Canonical URL |
|---|---|---|---|
| amazon | `amazon.in`, `www.amazon.in`, `m.amazon.in` | `/dp/{ASIN}`, `/{slug}/dp/{ASIN}`, `/gp/product/{ASIN}`, `/gp/aw/d/{ASIN}` (ASIN = 10 chars A-Z0-9) | `https://www.amazon.in/dp/{ASIN}` |
| flipkart | `flipkart.com`, `www.flipkart.com`, `dl.flipkart.com` | `/{slug}/p/{itm}` with query `pid={PID}` (PID required) | `https://www.flipkart.com/{slug}/p/{itm}?pid={PID}` |
| blinkit | `blinkit.com` | `/prn/{slug}/prid/{id}` | `https://blinkit.com/prn/{slug}/prid/{id}` |
| zepto | `zeptonow.com`, `www.zeptonow.com`, `zepto.com`, `www.zepto.com` | `/pn/{slug}/pvid/{uuid}` | `https://www.zeptonow.com/pn/{slug}/pvid/{uuid}` |
| instamart | `swiggy.com`, `www.swiggy.com` | `/instamart/item/{id}` (query ignored) | `https://www.swiggy.com/instamart/item/{id}` |

Short links (`amzn.in`, `amzn.to`, `fkrt.it`, `dl.flipkart.com/s/…`) → ValueError
`"Short links can't be read without opening them. Open the link in your browser and paste the full address."`.
Any other host, non-https, or a missing id → ValueError naming what's missing. Tracking query params are always dropped (except Flipkart's `pid`).

## Schema: `custom_listing`
`id` (int PK), `household_id` FK, `listing_id` str unique (`"cus-{id}"`, set after insert), `platform`, `sku`, `url` (canonical),
`title` 1..120, `brand` 1..40, `pack_label` (must `parse_pack`), `category` (one of the seed categories or a new lowercase slug 1..30),
`product_key` (slug: `{brand}_{title words}_{pack}` lowercased, `[a-z0-9_]`, max 60, unique per household. Add `_2`, `_3` on clash),
`family_key` (lowercase slug 1..40: an existing family or a new one), `icon` str default "🛒", `archived` bool, `created_at`.
UNIQUE (household_id, platform, sku) among non-archived.

## Catalog merge (`catalog.py`)
`current_listings(session, household_id, now)` now returns seed **plus** the household's non-archived custom listings, as `CurrentListing`s
built from a `SeedListing`-shaped value (`id = listing_id`, `url`, `member_discount` from the latest observation as today). A custom listing's
price comes **only** from its observations (created with one on POST). Other households' custom listings are never visible.

## API (`listings.router`, prefix `/api/v1`. The lead wires it.)
- `POST /listings/parse` `{url}` → `{platform, sku, url}` or 422 with the message (lets the UI show the platform before the form).
- `POST /listings` `{url, title, brand, pack_label, category, family_key, listed_paise, mrp_paise, member_price_paise?, in_stock?}` → 201
  with the listing (listing_id, product_key, all fields) **and** creates the first `price_observation` (source `"manual"`) with the same
  validation as `POST /prices`. Duplicate (platform, sku) → 409. Invalid → 422.
- `GET /listings?include_archived=false` → household custom listings + latest price/freshness.
- `PATCH /listings/{listing_id}` (title, brand, pack_label, category, family_key, icon, archived) → re-validated. 404 for other households.
- `GET /catalog/families` → sorted distinct family keys across the seed + household custom listings, each with a count and units (for the UI picker).

## Test cases (write first)
1. URL parsing, one test per row of the table, with real-looking URLs including tracking params, `m.` hosts and slugs. Canonical output exact.
   Amazon `https://www.amazon.in/Amul-Butter-500g/dp/B00ZXUW9ZK/ref=sr_1_1?keywords=amul+butter` → sku `B00ZXUW9ZK`, url `https://www.amazon.in/dp/B00ZXUW9ZK`.
   Flipkart without `pid` → ValueError. Short links → the exact message above. `http://` → ValueError. `https://www.bigbasket.com/pd/1/` → ValueError.
2. POST /listings creates `cus-1` with a slug product_key and an observation. `GET /deals` includes it with `price_source "manual"`. An exact need on
   its product_key plans to it. A family need on its family_key (with quantity in its unit) considers it alongside seed items.
3. Duplicate (platform, sku) → 409. The same sku after archiving → allowed.
4. Validation: bad pack_label, unknown platform URL, title too long, `mrp < listed`, `member > listed` → 422.
5. Product_key clash → `_2` suffix.
6. Isolation: household 2's custom listing (inserted directly) never appears in household 1's deals, plans, families or listings, and its
   listing_id as a filler/need → 422 for household 1.
7. PATCH archive → disappears from deals/plans. A saved list need referencing it → that line becomes `unpriced`.
8. `GET /catalog/families` includes seed families (e.g. `sunflower_oil`) and new ones (e.g. `cheese_slices`).
9. Migration 0005 upgrades from 0004 with data intact.

## Done when
- [ ] All cases pass. The full suite passes 3× in a row. mypy and ruff are clean. Commit on `feat/custom-listings` (no push). `handoff` + `release`.

## Don'ts
No network calls, no new dependencies. Don't edit `app/main.py` or `web/`. Use `grep` for exploring the seed, not inline `python -c`.
One command per call, foreground only.
