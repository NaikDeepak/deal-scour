# Task: Find on shops, Zepto prices and silent shops

**Assigned to:** agy (model: gemini-3.8-flash-high)  **Lead / reviewer:** claude  **Second review:** codex (read-only)
**Branch:** `fix/finder-zepto-instamart` (from `main`)  **Worktree:** `../deal-scour-wt-agy`

## Goal
The lead re-ran **Find on shops** for "Sunflower Seeds 500g" with extension 0.3.3. Amazon, Flipkart and Blinkit now behave. Fix these:

| # | Seen | Why |
|---|---|---|
| 1 | Every Zepto result shows **₹129**, and titles read "ADD₹129₹189₹60OFFFarmley Premium Sunflower Seeds1 pack (250 g)4.7(4.7k)" | On Zepto the `<a href=".../pvid/...">` **is** the whole card (button, prices, name, pack all inside it). `findCardForAnchor` starts at the anchor's **parent**, which is the grid of 6 cards, so every card reads the grid's first ₹. The title is the anchor's full text |
| 2 | A Zepto **sponsored** card is returned | Zepto marks ads with an `<img alt="P3 - Ad.png">` inside the card; `isSponsoredElement` doesn't know it |
| 3 | **Instamart** shows nothing at all, not even "no results" | Its search page has **zero** `<a href>` (cards are click handlers, like Blinkit). And when a shop's tab doesn't reach `complete` within the timeout, or a script throws, the worker pushes **nothing** for that shop (`service-worker.js` ~L575–625) |

Zepto card structure (seen live, 2026-10-19):
```html
<div class="grid ...">                         <!-- 6 cards per grid -->
  <a class="B4vNQ oikWp" href="/pn/nutraj-sunflower-seeds/pvid/c3480d95-a311-43ca-8429-27fe7dfeb40a">
    <img alt="Nutraj Sunflower Seeds"><img alt="P3 - Ad.png">
    <button>ADD</button>
    <span>₹75</span><span>₹199</span><span>₹124</span><span>OFF</span>   <!-- selling, MRP, saving -->
    <span>Nutraj Sunflower Seeds</span><span>1 pack (200 g)</span><span>4.6</span><span>(7.8k)</span>
  </a>
  <a href="/pn/farmley-premium-sunflower-seeds/pvid/29e56d16-...">... ₹129 ₹189 ₹60 OFF Farmley Premium Sunflower Seeds 1 pack (250 g) ...</a>
</div>
```

## Files you may touch (nothing else)
- `extension/finder.js`, `extension/service-worker.js`, `extension/manifest.json` (version → **0.3.4**), `extension/tests/*` (new fixture
  `extension/tests/fixtures/zepto-search.html`)
- `web/src/features/catalog/FindOnShops.tsx`, `web/src/features/catalog/FindOnShops.test.ts`

## Changes
1. **An anchor that holds a price is its own card.** In `findCardForAnchor`, if the anchor's own text contains `₹`, the card is the anchor
   (still run the sponsored check on it and on its ancestors up to the first card marker). Amazon/Flipkart behaviour must not change.
2. **Title for whole-card anchors.** When the anchor text contains `₹`, the title is the first `img[alt]` in the card whose alt is not an ad
   marker and is longer than 3 characters. If there is none, fall back to the existing rule. Never return a title that contains `₹`.
3. **Zepto ads.** `isSponsoredElement` (or the card check) treats a card containing an `img` whose alt matches `/\bad\b/i` (e.g.
   "P3 - Ad.png") as sponsored. "ADD" button text and words like "Badam" must not match.
4. **Every shop reports.** For each target the worker pushes exactly one of: its candidates, or `{platform, status: 'no_links', search_url}`.
   That includes tab timeout, script error, and an empty result. Update the Case 18 timeout test, which currently expects `[]`, to expect the
   `no_links` entry.
5. **Instamart message.** FindOnShops shows Instamart like Blinkit: "Instamart: no product links on its search page. **Open search on Instamart
   ↗**, open the right product and paste its link in Prices → Add a product." Make it one rule for both shops (no copy-paste of the block).
   Other shops keep "No results on {shop}. Open search ↗".

## Test cases (write first)
1. Zepto fixture (the structure above, 4 cards: 1 ad + 3 normal, distinct prices ₹75/₹37/₹129/₹73): `extractCandidates` returns the 3 non-ad
   cards with titles "Daily Good Sunflower Seeds" etc. (no `₹`, no "ADD"), prices 3700/12900/7300 paise in card order, packs 100g/250g/200g.
2. The Amazon and Flipkart fixture tests still pass unchanged.
3. Ad matcher: alt "P3 - Ad.png" → sponsored; alts "Badam Giri", "Add to cart", "ADD" → not sponsored.
4. Worker: tab never completes → response `results` is `[{platform:'amazon', status:'no_links', search_url}]`; `executeScript` throws →
   same shape; tab removed in both.
5. FindOnShops: a `no_links` result for `instamart` renders "Open search on Instamart ↗" with its `search_url`; `zepto` renders
   "No results on Zepto".

## Done when
- [ ] All cases pass; full suites green (extension `node --test extension/tests/*.test.js`; web vitest/eslint/tsc;
      `scripts/check-extension-version.sh`). Backend untouched.
- [ ] Commit on `fix/finder-zepto-instamart` (no push). `handoff` + `release`.

## Don'ts
No clicking or typing on shop pages. No new deps. Don't touch the backend. One command per call, foreground only, no inline `python -c`
or `node -e`.
