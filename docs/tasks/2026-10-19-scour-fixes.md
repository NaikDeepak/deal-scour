# Task: fix the scour extension and one-click bundle (review findings)

**Assigned to:** agy  **Lead / reviewer:** claude  **Second review:** codex (read-only)
**Branch:** `feat/scour-matrix-extension` (continue on it)  **Worktree:** `../deal-scour-wt-agy` (the branch is now checked out there; do not use the main checkout)

## Goal
Keep the price matrix, `/prices/capture` and the extension, but make sure nothing invented ever looks like a real price or a real offer,
the extension only saves prices it is confident about, and auto-add to cart is polite and only clicks the right product's button.

## Files you may touch (nothing else)
- `backend/app/domain/bundles.py`, `backend/app/api/v1/lists.py` (quick-bundle only), `backend/app/api/v1/prices.py` (capture only)
- `backend/tests/api/test_scour_capture.py`
- `extension/*` (incl. new `extension/lib.js`, `extension/tests/*.test.js`)
- `web/src/features/plans/{PlansPage.tsx,cartBuilder.ts,cartBuilder.test.ts}`, `web/src/features/baskets/BasketsPage.tsx`, `web/src/lib/api.ts`

Do **not** edit `docs/` (the lead writes ADR-025 and the FLOW update).

## Runtime boundary
Backend: server. Extension: Chrome MV3, plain JS, **no new dependencies**. Extension tests use `node --test extension/tests` with
plain objects (no jsdom). Money is integer paise everywhere.

## Changes
### A. Quick bundle adds needs only (blocker)
1. `apply_dryfruits_500g_bundle` only adds the 8 family needs (`DRYFRUITS_500G_NEEDS`) to the list. **Delete** `DRYFRUITS_500G_LISTINGS`
   and `DRYFRUITS_DEFAULT_OFFERS` and all code that inserts `CustomListing`, `PriceObservation` or `Offer`. The file should shrink to ~50 lines.
2. Families with no listing in the household catalog stay as needs; plans already report them as unpriced. Response adds
   `unpriced_families: list[str]` (families in the bundle with no current listing) so the UI can say "Add a product link for: walnuts, chia seeds".
3. Needs already on the list (same family_key + quantity, open) are not duplicated.

### B. `/prices/capture` (should fix)
4. Only for listings whose `url` is a real product page: reject (422) when the listing's url fails `sources.urls.parse_product_url`.
   URL matching uses `parse_product_url(req.url).url` (canonical) against listing urls, not string trimming.
5. Reject a capture whose `listed_paise` differs from the listing's latest price by more than 60% in either direction unless `confirm: true`
   (422 "Price changed a lot. Check the page and confirm."), so a misread page can't silently poison plans.

### C. Extension price extraction (should fix)
6. Move pure helpers into `extension/lib.js` (also `module.exports` for tests): `parseRupeesToPaise`, `priceFromJsonLd(texts[])`,
   `isAllowedUrl(url)` (https + host exactly one of amazon.in, www.amazon.in, flipkart.com, www.flipkart.com, blinkit.com, www.swiggy.com,
   www.zeptonow.com, zeptonow.com, zepto.com, www.zepto.com), `pickAddButton(candidates, packLabel)`.
7. **Remove the "first ₹ on the page" fallback.** Non-Amazon pages: JSON-LD `Product.offers.price` only, otherwise return null
   (the result says "Couldn't read the price on this page" and nothing is saved). Amazon keeps its selectors plus JSON-LD.
8. Service worker refuses any target/item whose url fails `isAllowedUrl` (result `ok:false, error:"Not a supported shop link"`) and
   never opens it.
9. Politeness: at most **15** targets per scour run; at least **8 s** between tab opens to the same host (sequential). Same for add-to-cart.

### D. Auto-add to cart (keep, harden)
10. Only search-page urls are opened but **never auto-clicked**: if the url is not a product page (`/dp/`, `/p/` with pid, `/prid/`, `/pvid/`,
    `/instamart/item/`), open it and return `added:false, reason:"Search page: pick the product yourself"`.
11. `pickAddButton`: prefer platform-specific ids (`#add-to-cart-button`, `button[name="submit.add-to-cart"]`); otherwise accept a generic
    "Add"/"Add to cart" button only if it is the **only** visible match on the page. Zero or several matches → don't click, leave the tab open.
12. Never click anything containing "Buy now", "Place order", "Checkout", "Proceed", "Pay". Stop after add-to-cart. Leave the last tab focused
    on the cart so the human checks out.
13. Web: the button says "Add to {Platform} cart" (no emoji), shows the per-item result list (added / opened for you / failed), and without the
    extension just opens the product tabs as today.

## Test cases (write first)
1. Quick bundle: adds 8 needs, inserts **zero** rows in custom_listing, price_observation and offer (count before/after). Running it twice adds 0.
   `unpriced_families` lists bundle families with no listing (seed has almonds/cashews/walnuts? assert against the real seed).
2. Capture by a tracking-param Amazon url matches the canonical listing. Capture for a listing with a search url → 422.
3. Capture 70% below the latest price → 422; with `confirm: true` → 201. 30% below → 201.
4. `parseRupeesToPaise("₹1,299.50") === 129950`; junk → null.
5. `priceFromJsonLd` reads Product offers (object and array), ignores malformed JSON, returns null without Product.
6. `isAllowedUrl`: allowed hosts true; `http://`, `amazon.in.evil.com`, `evil.com/?u=amazon.in` false.
7. `pickAddButton`: Amazon id wins; one generic "Add" → it; two generic "Add" → null; a "Buy now" only → null.
8. cartBuilder: search-url items are flagged `autoClick:false`.
9. Full suites: backend pytest, ruff, mypy; web vitest, eslint, tsc; `node --test extension/tests`.

## Done when
- [ ] All cases pass; full suites pass 3× in a row. Commit on `feat/scour-matrix-extension` (no push). `handoff` + `release`.

## Don'ts
No new deps, no proxies, no CAPTCHA handling, no clicking past add-to-cart. No inline `python -c`. One command per call, foreground only.
