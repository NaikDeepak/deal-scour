# Task: catalog pick list + "Find on shops"

**Assigned to:** agy (model: gemini-4-argon-high)  **Lead / reviewer:** claude  **Second review:** codex (read-only)
**Branch:** `feat/catalog-finder` (from `main` after `feat/staples-tracker` merges)  **Worktree:** `../deal-scour-wt-agy`

## Goal
The owner has two CSVs of products they buy: `data/deal_scourer_seed_catalog_500_products.csv` (500 products) and
`data/deal_scourer_dryfruit_seed_catalog.csv` (250). Each product has 4 rows (one per shop), and the rows hold **search** URLs only, with no prices.
Afterwards:
1. All 750 products are a searchable **pick list**. Typing "toor" in "Add an item…" on a list offers "Tata Sampann Toor/Arhar Dal 600 g".
2. Picking one adds a flexible need, e.g. family `toor_dal`, `600g`.
3. **Find on shops** on a need, or on a catalog product, makes the extension open each shop's search in background tabs. It brings back
   the top product pages (title, url, price, pack). The owner ticks the right ones and they become tracked listings.
   Nothing is tracked without that tick.

Also: support Instamart's new product links, `https://instamart.in/p/<slug>-<ID>` (e.g. `…/p/tata-sampann-pure-cashews-whole-kaju-nutritious-delicious-T6LJGMXRBD`).

## Files you may touch (nothing else)
- `backend/app/domain/models.py` (`CatalogProduct`), `backend/migrations/versions/0008_catalog.py` (new)
- `backend/app/domain/catalog_import.py` (new: CSV → `CatalogProduct` rows, family/pack rules), `backend/app/jobs/import_catalog.py` (new CLI)
- `backend/app/api/v1/catalog.py` (new router), `backend/app/sources/urls.py` (instamart.in), `backend/app/sources/autofill.py` (only to share/extend
  the keyword→family table: add almonds, cashews, raisins, walnuts, pistachios, dates, pumpkin/sunflower/chia/flax seeds, toor/moong/chana/urad dal,
  rice, poha, besan, sooji, rajma, masala names…)
- `backend/tests/domain/test_catalog_import.py`, `backend/tests/api/test_catalog.py`, `backend/tests/sources/test_urls.py`, `backend/tests/test_migrations.py`,
  `backend/tests/fixtures/catalog_sample.csv` (new: 3 products × 4 rows, copied in format from the real files)
- `extension/finder.js` (new content script for search pages), `extension/service-worker.js`, `extension/portal-bridge.js`, `extension/lib.js`,
  `extension/manifest.json`, `extension/tests/*.test.js`, `extension/tests/fixtures/*.html` (small hand-made search-page snippets)
- `web/src/features/list/*` (catalog search in "Add an item…"), `web/src/features/catalog/FindOnShops.tsx` (new), `web/src/lib/api.ts`,
  `web/src/lib/links.ts` (instamart.in), matching `*.test.ts`

## Runtime boundary
- **CLI (server machine):** `python -m app.jobs.import_catalog <csv> --household 1` reads a CSV from disk. Re-running it is safe: upsert on
  (household, seed_product_id). The CSV is untrusted text: validate lengths (name ≤ 160, brand ≤ 80), ignore its notes and verification columns,
  and never fetch its URLs.
- **Server:** stores catalog products and builds shop search URLs itself from name + pack. The CSV's URLs are not used, except a row whose `url_type` is
  "Direct product URL" and which passes `parse_product_url`; that becomes a pre-filled suggestion. The server **never fetches search pages**.
- **Extension:** the only thing that opens search pages. It runs in the owner's browser at the owner's pincode, one shop at a time,
  ≥ 3 s between shops, ≤ 5 results per shop, each tab closed after reading. It only reads; it never clicks, adds to cart or types.
- **Web:** shows candidates as the API/extension return them. No ranking logic beyond what the API sends.

## A. Import
1. Columns: `seed_product_id, product_name, brand, category, target_pack_weight_g, platform, url, url_type, …`. Group rows by `seed_product_id`.
   Name: strip " (target 600 g)". Pack label from `target_pack_weight_g` (`600` → `600g`, `1000` → `1kg`). `family_key` from the keyword rules
   on the name, otherwise a slug of the category (e.g. `dal_pulses`). Keep `category`.
2. Report: `{created, updated, skipped: [{seed_product_id, reason}]}`. Bad rows are skipped and reported; they never abort the import.

## B. API (household-scoped, CSRF header as usual)
3. `GET /catalog?q=&limit=20`: case-insensitive match on name/brand words. All words must match ("tata toor" matches; "tata rice" doesn't
   match the dal).
4. `GET /catalog/{id}/search-urls` → `[{platform, url}]` for the 5 shops, built from `brand + name + pack`:
   - Amazon: `https://www.amazon.in/s?k=…`
   - Flipkart: `https://www.flipkart.com/search?q=…`
   - Blinkit: `https://blinkit.com/s/?q=…`
   - Zepto: `https://www.zepto.com/search?query=…`
   - Instamart: `https://www.swiggy.com/instamart/search?query=…`
   Use only these 5 hosts, with the query URL-encoded.
5. `POST /catalog/{id}/candidates` `{results: [{platform, url, title, price_paise|null, pack_label|null}] ≤ 25}` → the server keeps only URLs that pass
   `parse_product_url`, then scores each one for display:
   - +2 brand word in title
   - +2 pack matches the target within ±10%
   - +1 per name word in title
   It returns them sorted, with `pack_matches: bool`. It never picks one itself: no confident match means no match (AGENTS §4.9).
   Nothing is saved.
6. Saving a ticked candidate uses the existing `POST /listings` (family and category from the catalog product, price from the candidate).
   An existing listing with the same canonical URL → reuse it, no duplicate.

## C. Extension
7. New message `DEALSCOUR_FIND_PRODUCT {catalogId, targets: [{platform, url}]}`, sent from the portal through `portal-bridge.js`, only from the
   DealScour origin, as for scour. The worker opens each search url in a background tab. `finder.js` collects anchors whose href passes
   `isProductPageUrl`, takes the nearest card's text for title, price (`parseRupeesToPaise`) and pack (`\d+(\.\d+)? ?(g|kg|ml|l)`), dedupes by product id,
   and keeps the first 5. Progress messages go back to the page as for scour. Each tab is closed after reading; a 20 s timeout per shop skips that shop.
8. `lib.js`: `isProductPageUrl` and `extractProductId` accept `instamart.in/p/<slug>-<ID>` (ID = trailing `[A-Z0-9]{8,}`).

## D. Web
9. "Add an item…" also searches the catalog (debounced 250 ms, ≤ 8 shown under a "From your catalog" heading). Picking one adds a family need with
   the catalog pack.
10. **Find on shops** button on a catalog-backed need, and next to catalog search results. It opens `FindOnShops`:
    - live progress ("Searching Flipkart… 3 found")
    - then candidates grouped by shop: title, pack (green if it matches), price, and an "Open ↗" link
    - a checkbox on each candidate, then **Track selected**
    If the extension isn't installed: "Install the DealScour extension to search shops" plus plain search links per shop.

## Test cases (write first; fixtures only, no network)
1. Import `catalog_sample.csv`: 3 products created, name has no "(target …)", pack `600g`/`1kg`, family from rules (`toor_dal`, `almonds`) or the category slug.
2. Re-import: 0 created, 3 updated. A row with an empty name or a 300-char name → skipped with a reason; the others still import.
3. The direct-product-URL row becomes a suggestion; a search-URL row doesn't.
4. `GET /catalog?q=tata toor` → the dal; `q=tata rice` → not the dal. Another household's catalog → never returned.
5. `search-urls` → 5 urls, encoded, only the 5 allowed hosts.
6. `candidates`: a non-product url is dropped. Brand + pack match ranks first; `pack_matches` is right at ±10%. Nothing is written to the DB.
7. `parse_product_url("https://instamart.in/p/tata-sampann-pure-cashews-whole-kaju-nutritious-delicious-T6LJGMXRBD")` → instamart, sku `T6LJGMXRBD`,
   canonical `https://instamart.in/p/…-T6LJGMXRBD` (keep the slug). The old swiggy form still works.
8. Extension: `extractCandidates(fixtureDom)` for an Amazon and a Flipkart search snippet → ≤ 5 deduped candidates with price and pack; ads or
   non-product links are ignored. `isProductPageUrl` accepts instamart.in/p/…-ID and rejects instamart.in/search.
9. Web: catalog results render under "From your catalog"; FindOnShops shows the no-extension fallback; links.ts accepts instamart.in product links.
10. Migration 0008 upgrades from 0007 with data intact.

## Done when
- [ ] All cases pass; full suites 3× green (backend pytest, ruff, mypy; web vitest, eslint, tsc; `node --test extension/tests/*.test.js`).
- [ ] Commit on `feat/catalog-finder` (no push). `handoff` + `release`.

## Don'ts
No new deps. Don't edit `app/main.py` (the lead wires the router). Don't fetch search pages from the server. Don't auto-track a candidate.
No clicking or typing on shop pages. No inline `python -c`. One command per call, foreground only. Don't touch `data/` (the lead runs the import).

## Round 2 (review by claude + codex) — same branch; files above plus `web/src/features/plans/PlansPage.tsx`
11. **Wire it in.** `CatalogPicker` and `FindOnShops` are not used anywhere. The "Add an item…" box lives in `PlansPage.tsx` (spec error, sorry):
    show catalog results there under "From your catalog", and put a **Find on shops** button on each open need that came from the catalog (and on
    catalog results). Keep the existing add-item behaviour for seed products.
12. **Search URLs only.** Add `isAllowedSearchUrl(url, platform)` in `lib.js`: https, exact host and path per platform, query param present:
    - amazon: `www.amazon.in/s?k=`
    - flipkart: `www.flipkart.com/search?q=`
    - blinkit: `blinkit.com/s/?q=`
    - zepto: `www.zepto.com/search?query=`
    - instamart: `www.swiggy.com/instamart/search?query=`
    The finder worker opens a target only if it passes for that target's own platform. Product pages and other paths are refused.
13. **Portal origin allow-list.** `PORTAL_ORIGINS = ['http://localhost:8000', 'http://127.0.0.1:8000', 'http://localhost:5173', 'http://127.0.0.1:5173']`
    in `lib.js`. Manifest content-script `matches` are narrowed to those 4 origins. `portal-bridge.js` ignores all messages unless
    `location.origin` is in the list. The worker handles `DEALSCOUR_FIND_PRODUCT` and `DEALSCOUR_RUN_SCOUR` only when
    `sender.id === chrome.runtime.id` and `new URL(sender.tab.url).origin` is in the list.
14. **Timeout really skips.** `waitForTabComplete` returns `'complete' | 'timeout'`. On timeout, close the tab and skip extraction for that shop.
15. **One find at a time.** A second `DEALSCOUR_FIND_PRODUCT` while one is running → `{ok: false, error: 'A search is already running.'}`.

Test cases (write first):
16. `isAllowedSearchUrl`: accepts the 5 shapes; rejects an amazon `/dp/` url, a flipkart search url sent as platform `amazon`, http, and a lookalike host.
17. Worker sender check: wrong origin or foreign `sender.id` → ignored; allowed origin → runs (with fake `chrome`).
18. Timeout → no `executeScript` on that tab and the tab is removed. A second find while running → the error above.
19. Web: on the Plan page, typing "toor" shows the catalog result; a catalog need shows **Find on shops**.

Full suites 3×, commit on feat/catalog-finder, handoff + release.
