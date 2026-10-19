# Task: Find on shops, fixes from the first real run

**Assigned to:** agy (model: gemini-3.8-flash-high)  **Lead / reviewer:** claude  **Second review:** codex (read-only)
**Branch:** `fix/finder-real-run` (from `main`)  **Worktree:** `../deal-scour-wt-agy`

## Goal
The lead ran **Find on shops** for real (walnuts, cashews) on 2026-10-19. The flow works end to end (search, candidates, Track selected →
listing), but it has these problems. Fix all of them.

| # | Seen | Why |
|---|---|---|
| 1 | Zepto returned 0 results, though its search page has ~30 `/pn/` product links | It renders results ~2–4 s **after** the tab reports `complete`; `finder.js` reads too early |
| 2 | Blinkit (and likely Instamart) returned 0, silently | Their search results have **no product links** (cards are click handlers; no ids in the DOM or JSON-LD). We never click shop pages |
| 3 | A result with no pack (most Flipkart results) is saved with the **catalog's** pack (500g) when it's really 200g | `FindOnShops.tsx:81` `c.pack_label \|\| product.pack_label` |
| 4 | "Kashmiri Walnut Kernels 200 Gram (Pack Of 2)" parsed as **100g** | the pack regex misses `Gram`/`Grams` and ignores "Pack of N" |
| 5 | Tracked "Deluxe Walnut Kernels" (Amazon) saved with brand **Happilo** | brand comes from the catalog product, not the candidate |
| 6 | Category saved as `dry_fruits_nuts`, `cashews`, … while the app uses `dryfruits`, `staples`, `dairy`, … | the importer keeps CSV category slugs |
| 7 | **Find on shops** on a list item that isn't in the catalog (e.g. "Sunflower Seeds 500g") does nothing, with no message | `CatalogPicker.tsx` only searches the catalog for an exact match |

## Files you may touch (nothing else)
- `extension/finder.js`, `extension/service-worker.js`, `extension/lib.js`, `extension/manifest.json` (version → **0.3.3**), `extension/tests/*`
- `backend/app/api/v1/catalog.py`, `backend/app/domain/catalog_import.py`, `backend/app/sources/autofill.py` (only to reuse/export `_extract_brand`,
  `_extract_pack_label`), `backend/tests/api/test_catalog.py`, `backend/tests/domain/test_catalog_import.py`
- `backend/migrations/versions/0010_catalog_categories.py` (new, data-only: remap existing `catalog_product.category` and `custom_listing.category`)
- `web/src/features/catalog/FindOnShops.tsx`, `web/src/features/list/CatalogPicker.tsx`, `web/src/lib/api.ts`, matching `*.test.ts`

## Changes
1. **Wait for results.** After `complete`, `finder.js` polls every 500 ms for up to 8 s until at least one product link is found (or time
   runs out), then extracts. Still read-only.
2. **No-link shops say so.** If a shop gives 0 candidates, the worker returns `{platform, status: 'no_links', search_url}`. FindOnShops shows
   "Blinkit: no product links on its search page. **Open search on Blinkit ↗**, open the right product and paste its link in Prices → Add a
   product." Use the same pattern for any shop with 0 results ("No results on Zepto. Open search ↗").
3. **Pack must be known before tracking.** A candidate with no `pack_label` shows a small pack input ("e.g. 200g"). Its checkbox stays disabled
   until a valid pack is typed (use `parse_pack` rules on the server; the web only shows what the API says). Never fall back to the catalog pack.
   `POST /catalog/{id}/candidates` returns `pack_label: null` for unknown, never a guess.
4. **Pack parsing** (shared helper, used by `finder.js` and the server scorer):
   - `g|gm|gms|gram|grams|kg|kgs|ml|l|ltr|litre`, case-insensitive
   - "Pack of N" / "(Pack Of N)" / "N x 200g" multiplies: "200 Gram (Pack Of 2)" → 400g; "3 x 200g" → 600g
   - ambiguous → null
5. **Brand from the candidate, not the catalog.** The server computes `brand` per candidate with the autofill rule (known brand list, else the
   first word of the title). Saving uses that brand. If the candidate title contains the catalog brand, use the catalog brand.
6. **One category vocabulary.** The importer maps CSV categories to the app's: `Dry Fruits & Nuts`, `Almonds`, `Cashews`, `Raisins` → `dryfruits`;
   `Dal & Pulses`, `Rice, Grains & Flours`, `Spices & Masalas`, `Cooking Essentials`, `Packaged Ready Mixes` → `staples`;
   `Breakfast & Cereals` → `breakfast`; `Snacks & Savoury` → `snacks`; unknown → `staples`. Migration 0010 remaps existing rows in
   `catalog_product` and `custom_listing` the same way (`dry_fruits_nuts`, `cashews`, `almonds`, `raisins` → `dryfruits`, and so on). It's
   reversible as a no-op downgrade.
7. **Find on shops without a catalog item.** `GET /catalog/search-urls?q=<text>` (household-scoped auth, same 5 hosts, query ≤ 80 chars) and
   `POST /catalog/candidates?q=<text>&pack=<label>` score against the free text instead of a catalog row. In `CatalogPicker`, a need with no exact
   catalog match uses the need's own name and pack ("Sunflower Seeds", "500g"). It never silently does nothing.

## Test cases (write first)
1. finder: a fake DOM that gets product links 1.5 s after "complete" → found (fake timers). No links after 8 s → `no_links`.
2. Pack: "200 Gram (Pack Of 2)" → 400g; "Pack of 3 x 200g" → 600g; "1 Kg" → 1kg; "Premium Walnuts" → null; "500gm" → 500g.
3. Candidates: a Flipkart candidate with no pack → `pack_label: null`; the web disables its checkbox until "200g" is typed, and the save
   sends 200g (not the catalog's 500g).
4. Brand: title "Deluxe Walnut Kernels 200g" for catalog brand Happilo → brand "Deluxe"; title "Happilo Premium Walnuts" → "Happilo".
5. Import: "Cashews" → `dryfruits`, "Dal & Pulses" → `staples`. Migration 0010: rows with `dry_fruits_nuts`/`cashews` become `dryfruits`;
   data otherwise intact.
6. Free-text find: `search-urls?q=Sunflower Seeds 500g` → 5 allowed URLs; the web's Find on shops on a non-catalog need opens the panel.
7. FindOnShops renders "Open search on Blinkit ↗" for a `no_links` shop.

## Done when
- [ ] All cases pass; full suites 3× green (backend pytest/ruff/mypy; web vitest/eslint/tsc; extension tests; `scripts/check-extension-version.sh`).
- [ ] Commit on `fix/finder-real-run` (no push). `handoff` + `release`.

## Don'ts
No clicking or typing on shop pages (Blinkit stays "open search" only). No new deps. Don't edit `app/main.py`. One command per call, foreground
only, no inline `python -c`.
