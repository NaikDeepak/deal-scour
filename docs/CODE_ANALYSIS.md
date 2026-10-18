# Prototype Code Analysis

*Analysis of `dealscour_v3.html` and `deal_scour_backend.py` as of 2026-10-18.*

## 1. Inventory

| File | Size | What it is |
|---|---|---|
| `dealscour_v3.html` | 2,692 lines / 1.0 MB | Single-page UI with Tailwind via CDN play script, vanilla JS, localStorage. **~870 KB (87%) is one inline base64 hero JPEG on line 136.** |
| `deal_scour_backend.py` | 402 lines | Dataclasses + `DealScourEngine` with a hard-coded 8-item catalog and a one-shot wishlist scan. The same file is embedded as text in the HTML's "Architecture" tab. |
| `.qodo/` | empty | Qodo agent/workflow folders, unused. |

## 2. What the prototype does

### UI (`dealscour_v3.html`)
| Tab / area | Behaviour | Key functions (JS, approx. line) |
|---|---|---|
| Header | Pincode modal (6-digit validation, city presets), theme toggle, cart button | `initEvents` (~2424) |
| Membership bar | Toggle Prime / Swiggy One / Flipkart Plus / Zomato Gold / Zepto Pass → re-price everything | `renderMembershipBar` (~1750) |
| **Deals** | Search, presets, category pills, platform filter, 5 sort modes. Cards show landed price, unit rate, discount %, coupon text, "Lowest Landed Price" badge | `renderDeals` (~1835) |
| Compare modal | Peers in the same `itemGroup` **or the same category**, sorted by unit rate | `openComparisonModal` (~2135) |
| **Matrix** | Bar chart + table per item group | `renderMatrixView` (~2188) |
| **Cart** ("Smart basket") | List of items, three totals (single Amazon, single Blinkit, split), per-platform route steps, sample monthly basket | `updateCartUI` (~2035) |
| **Alerts** (Wishlist "cron") | Add watch (item, target, channel), list with HIT/MONITORING, cron schedule select, "Run now", fake logs | `renderWishlistCronView` (~2254), `executeManualCronJob` (~2334) |
| **Architecture** | Static explainer + Python script with copy button | — |
| "Live scour" | 3-step `setInterval` progress animation; **no network** | `triggerLiveScour` (~2365) |

Data: `DEALS_DATABASE` holds 35 listings across 12 `itemGroup`s (Amazon 10, Flipkart 6, Instamart 6, Blinkit 3, Zepto 3).
State: `appState` with memberships, cart, wishlist and cron logs. Cart, memberships, wishlist and theme persist to localStorage (`*_v3` keys).

### Backend (`deal_scour_backend.py`)
- `MembershipProfile`, `WishlistItem`, `ScouredProduct` dataclasses.
- `apply_membership_pricing`: net = listed − member discount + (fee unless member). Unit rate per 1 kg / 1 L / 100 g.
- `fetch_catalog_snapshot`: returns the hard-coded list, filtered by substring and sorted by unit rate. It is `async` but awaits nothing.
- `execute_wishlist_cron_cycle`: keyword match, then pick the cheapest match. Triggered if `price ≤ target OR discount ≥ min`.
- `__main__`: prints one scan. There is no loop, no persistence and no notifications.

## 3. Ideas worth keeping (port to the new app)
1. **Membership-aware landed price**: toggling a membership re-prices everything. Becomes `pricing/landed.py` with `platform_account` memberships.
2. **Unit-rate normalisation** (₹/kg, ₹/L, ₹/100 g) as the default sort. Becomes `pricing/units.py`.
3. **Cross-platform compare modal and matrix view.** These become Deals ▸ Compare.
4. **"Item + Delivery" breakdown on the card.** Keep it, but show delivery as an *order-level* condition ("free above ₹199").
5. **Sample monthly basket** → becomes the seeded "Monthly" list template.
6. **Wishlist with target price + channel** → becomes `watch` with ANY/ALL rules.
7. **Pincode-first design** → becomes `household.pincode`, and listings are per pincode.
8. Platform brand colours (`amazon #FF9900`, `flipkart #2874F0`, `blinkit #F8CB46`, `instamart #FC8019`, `zepto #9333EA`).

## 4. Defects & gaps (do not port)

| # | Severity | Where | Problem | Fix in new design |
|---|---|---|---|---|
| D1 | **High** | `deal_scour_backend.py` `execute_wishlist_cron_cycle` | Any query word longer than 2 chars matching title/brand counts as a match. **Verified by running it:** the *California Almonds* watch matches *Amul Ghee "Tin **Pack**"* and *India Gate "Bulk **Pack**"*, so it alerts "Almonds → ₹585 on Swiggy Instamart" using the ghee price. | Product/need matching with confidence (ADR-012); watches bind to product ids |
| D2 | **High** | HTML `updateSummaryStats`, `renderWishlistCronView`, `executeManualCronJob`, add-alert | `DEALS_DATABASE.find(...) \|\| DEALS_DATABASE[0]` falls back to the first item (Atta). Unmatched watches are evaluated against Atta's price, producing false "TARGET HIT — BUY NOW". | No-match means no-match (AGENTS.md invariant 9) |
| D3 | **High** | HTML `updateCartUI` | "Split savings" are **fabricated**: single-platform totals = `splitTotal × 1.07/1.15` (Amazon) and `× 1.09/1.18` (Blinkit). Nothing is computed. | Real optimizer (BASKET_OPTIMIZER.md) with an honest baseline |
| D4 | **High** | Both `apply_membership_pricing` / `recalculatePrices` | Delivery fee is added **per item**. A 5-item non-member basket is charged 5 fees. Free-delivery thresholds are ignored. Membership = always free, even though the code comment says Swiggy One is free only above ₹199. | Order-level fees with versioned fee schedules (ADR-011) |
| D5 | Med | HTML `renderDeals` | "Lowest Landed Price" winner is chosen by absolute price, not unit rate, across different pack sizes. | Compare by unit rate within a product family |
| D6 | Med | HTML `DEALS_DATABASE` | `wal-1` (Nutraj **walnuts**) has `itemGroup: "california_almonds"`, so walnuts compete with almonds. | Need → Product → Listing hierarchy |
| D7 | Med | HTML compare modal | Peers = same group **or same category**, so atta is compared with rice and oil. | Peers = same product, or the same flexible need |
| D8 | Med | Both | No real data: "live scour" is an animation, the pincode change only renames the label ("Pimpri-Chinchwad {pin}" for any pin), and the cron schedule select is cosmetic. Python `__main__` uses no scheduler or persistence. | Adapters + APScheduler + DB (ADR-004, ADR-014) |
| D9 | Med | Both | Pricing logic is duplicated in Python and JS with different data (8 vs 35 items) and rounding (`round(x,1)` vs `Math.round`). | One server-side implementation, paise (ADR-009, ADR-019) |
| D10 | Med | HTML everywhere | Strings are built into `innerHTML`, including user-entered watch text and (in future) scraped titles. That's an XSS risk once data is shared between family members. | Framework escaping, CSP |
| D11 | Med | Python | `triggered = price ≤ target OR discount ≥ min`. A 20% "discount" on an inflated MRP triggers even far above target. | Explicit ANY/ALL rule; unit-rate targets |
| D12 | Low | HTML cart | No quantities. One unit per listing. A duplicate add toggles it off. | `basket_line.qty` |
| D13 | Low | HTML | 870 KB inline image. Tailwind CDN play script isn't for production. Google Fonts are blocking. | Built CSS, optimised asset or none |
| D14 | Low | Python | Unused imports (`json`, `re`, `asdict`, `field`) and unused `logger`. `async` without awaits. `notify_channel` is never used. | — |
| D15 | Low | HTML | `discountPercent` is computed after the fee is added, so a non-member's "discount" drops because of delivery. That mixes two concepts. | Discount vs MRP on item price only; fees shown separately |
| D16 | Low | HTML | Wishlist auto-target = 95% of the current price, with `minDiscount` = current discount. With an OR rule it triggers immediately. | Sensible defaults from the 30-day low when there's history |

## 5. Mapping prototype → new modules

| Prototype piece | New home |
|---|---|
| `MembershipProfile` / `appState.memberships` | `platform_account.memberships` + Settings ▸ Accounts |
| `ScouredProduct` / `DEALS_DATABASE` entries | `product` + `listing` + `price_observation` (seed with `source="sample"`) |
| `apply_membership_pricing` / `recalculatePrices` | `pricing/landed.py`, `pricing/units.py`, `pricing/fee_schedules.py` |
| `fetch_catalog_snapshot` | `GET /deals` + `sources/*` adapters |
| `WishlistItem` / `appState.wishlist` | `watch` table, `jobs/scan_watches.py` |
| `execute_wishlist_cron_cycle` / `executeManualCronJob` | `jobs/scan_watches.py` + `POST /jobs/scan-watches/run` (admin) |
| `updateCartUI` "split arbitrage" | `optimizer/*` + Plans screen |
| `MEMBERSHIP_META.feeSaved` | `fee_schedule` rows |
| `cronLogs` | `job_run` table, Settings ▸ Jobs |
| Toasts, theme, pincode modal | `web/src/app/*` |

## 6. Seed data to carry over
The 35 prototype listings are a useful sample catalog for development. Import them via `backend/scripts/seed_from_prototype.py`
with `source="sample"`, after fixing D6 (walnuts get their own product). They make the UI usable on day one and give realistic golden-test inputs.
