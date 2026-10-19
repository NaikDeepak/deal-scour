# DealScour browser extension (optional)

Reads prices from shop pages in your own browser and can add a ready basket to a shop's cart. See ADR-025.

**Install (Chrome):** `chrome://extensions` → turn on Developer mode → **Load unpacked** → pick this `extension/` folder.
Then open DealScour at `http://localhost:8000`; the Plans tab shows "Check live prices and plan" once the extension is detected.

What it does and doesn't do:
- Opens only amazon.in, flipkart.com, blinkit.com, swiggy.com (Instamart) and zepto product links, one at a time, at most 15 per run.
- Saves a price only when the page states it clearly; otherwise it saves nothing.
- Add to cart starts only after you click **Add N items** in its own window. It never clicks Buy now, Checkout or Pay. You check out.

Tests: `node --test extension/tests/*.test.js`

## Find on shops

From a catalog item on the Plan page, **Find on shops** opens each shop's search page in a background tab, reads up to 5 product links with
price and pack, and closes the tab. It only accepts requests from DealScour (`localhost:8000` or the dev server on `5173`) and only opens the
5 shop search pages. It never clicks or types on the shop. You choose which results to track.

If you open DealScour on a different address or port, add it to `PORTAL_ORIGINS` in `lib.js` and `portal-bridge.js`, and to `matches` in
`manifest.json`, then reload the extension.
