# Task: staples tracker — quick add, price history, deal alerts

**Assigned to:** agy  **Lead / reviewer:** claude  **Second review:** codex (read-only)
**Branch:** `feat/staples-tracker` (from `main` after `feat/scour-matrix-extension` merges)  **Worktree:** `../deal-scour-wt-agy`

## Goal
The owner tracks ~25 staples (butter, cheese, bread, eggs, whey…). They can add a product by pasting just a link (the form fills itself),
paste several links at once, see each product's price history and 30-day low, set a "tell me below ₹X" target, and see a **Deals** list of
products that are at their 30-day low, below target, or ≥ 15% under their 30-day average.

## Files you may touch (nothing else)
- `backend/app/sources/autofill.py` (new), `backend/app/sources/gemini.py` (new)
- `backend/app/api/v1/listings.py` (autofill + history + target endpoints), `backend/app/api/v1/watch.py` (new: deals feed)
- `backend/app/domain/models.py` (`ListingWatch`, `LlmUsage`), `backend/migrations/versions/0007_watch.py` (new)
- `backend/app/core/config.py` (`gemini_api_key` ← `GEMINI_API_KEY`, `gemini_model` ← `DEALSCOUR_GEMINI_MODEL` default `gemini-3.8-flash`,
  `llm_monthly_cap_paise` ← `DEALSCOUR_LLM_MONTHLY_CAP_RUPEES` default 100)
- `.env.example` (document the three keys)
- `backend/tests/sources/test_autofill.py`, `backend/tests/api/test_watch.py`, `backend/tests/test_migrations.py`
- `web/src/features/prices/{PricesPage.tsx,AddProduct.tsx,PriceHistory.tsx}`, `web/src/features/deals/DealsPage.tsx` (new), `web/src/App.tsx` (add tab),
  `web/src/lib/api.ts`, matching `*.test.ts`

## Runtime boundary
Server-side only for fetching and Gemini (the key never reaches the browser, logs or the notepad). Gemini is optional: with no key everything
works using the rule-based path. No new Python deps: call the Gemini REST API with `httpx`. The web shows what the API returns (no pricing logic).

## A. Autofill (`POST /listings/autofill {url}`)
1. `parse_product_url` first (422 on bad links). Amazon/Flipkart: fetch the page once via the fetcher's `fetch_url` (same politeness lock,
   same allowed hosts) and read title, price, MRP, stock with the existing parsers (extend them to also return the product title).
   Quick-commerce links are **not fetched**: title comes from the URL slug only, price left empty for the user.
2. Rule-based suggestion from the title: `brand` (first word(s) matching a small brand list: Amul, Mother Dairy, Britannia, Epigamia, Eggoz,
   MuscleBlaze, Optimum Nutrition, Pintola, Quaker, Fortune, Tata Sampann, Aashirvaad, Saffola, Nestlé…; otherwise the first word),
   `pack_label` (regex for `\d+(\.\d+)?\s?(g|gm|kg|ml|l|ltr|pcs|pieces|pc)` and `\d+ ?lb` → grams), `family_key` (keyword map: butter, cheese slices,
   cheese block, paneer, bread, eggs, whey, peanut butter, oats, ghee, atta, oil, dal, yogurt…), `category`.
3. If any field is still missing **and** a Gemini key is set **and** this month's spend is under the cap: one Gemini call with the title only,
   asking for strict JSON `{brand, pack_label, family_key, category}`, validated by Pydantic; invalid → ignored. Record tokens and estimated cost
   in `LlmUsage`. Response says which fields came from `page`, `rules` or `gemini`. The user always confirms before saving.
4. `POST /listings/bulk {urls: [..≤20]}` → autofills each (sequential, politeness applies) and returns suggestions; nothing is saved until the
   user confirms each row (the web sends normal `POST /listings` calls).

## B. History and targets
5. `GET /listings/{id}/history?days=90` → observations (observed_at, listed, mrp, in_stock, source), plus `low_30d`, `avg_30d`, `high_30d`.
6. `ListingWatch(household_id, listing_id, target_paise null, created_at)`; `PUT /listings/{id}/watch {target_paise|null}`, `DELETE` to stop.
7. `GET /deals/feed` → watched or custom listings that are in stock and fresh/ok, with reasons: `below_target`, `low_30d` (current ≤ 30-day low and
   ≥ 3 observations), `under_avg` (≥ 15% under the 30-day average). Sorted by % saving. Never includes sample or stale prices.

## C. Web
8. Prices → **Add a product**: paste link → "Fill from link" → fields fill in (marked "from page / guessed / AI") → user edits → Save.
   A "Paste several links" box does the same for up to 20 rows in a table.
9. Each tracked product: sparkline of 90 days, "30-day low ₹X", and a target-price input.
10. New **Deals** tab first in the nav: the feed with reason chips, the shop, price vs 30-day average, and an "Add to list" button.

## Test cases (write first; no real network, fake http and fake Gemini)
1. Autofill an Amazon fixture page → title, price, MRP from page; brand "Amul", pack "500g", family "butter" from rules.
2. Title "Optimum Nutrition Gold Standard Whey 2 lb" → pack "907g", family "whey_protein".
3. Missing family, Gemini key set → fake Gemini returns JSON → used, `source=gemini`, usage row written. Bad JSON → ignored, no crash.
4. Gemini key empty → never called. Monthly cap reached → never called.
5. Quick-commerce link → no HTTP call, title from slug, price empty.
6. Bulk: 3 urls → 3 suggestions, nothing saved; > 20 → 422.
7. History stats: low/avg/high over 30 days with fixed clock.
8. Feed: below target, 30-day low, 15% under average each produce the right reason; stale or out-of-stock never appear; another household's never appear.
9. Gemini key never appears in responses or caplog.
10. Migration 0007 upgrades from 0006 with data intact.
11. Web: AddProduct fills fields from a mocked autofill; Deals renders reasons; vitest.

## Done when
- [ ] All cases pass; full suites 3× green; mypy, ruff, eslint, tsc clean. Commit on `feat/staples-tracker` (no push). `handoff` + `release`.

## Don'ts
No new dependencies. No Gemini calls in tests. Don't fetch quick-commerce sites. Don't edit `app/main.py` (lead wires the router). No inline `python -c`.
One command per call, foreground only.
