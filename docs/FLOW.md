# Flows

*User flows and system flows. Status: Design v1 · 2026-10-18*

Contents
1. Quick list → plan → order (the main loop)
2. Wishlist watch → alert → basket
3. Optimizer request (system sequence)
4. Pending basket lifecycle (state machine)
5. Filling a pending basket
6. Offer Wallet: add, use, expire
7. Household & circle: share, pool, settle up
8. Price refresh & freshness
9. Post-order reconciliation & savings ledger
10. Screen map

---

## 1. Quick list → plan → order

```mermaid
flowchart TD
  A["Type: atta 5kg, oil 5L, ghee 1L, surf 2L"] --> B["Parse → Needs<br/>qty · pack · brand-flex · need-by"]
  B --> C{"All lines matched<br/>to a product?"}
  C -- no --> C1["Pick from 3 suggestions<br/>or create product"] --> D
  C -- yes --> D{"Prices fresh?"}
  D -- stale/missing --> D1["Prompt: paste link or enter price<br/>(any household member)"] --> E
  D -- fresh --> E["Tap: Plan my list"]
  E --> F["Optimizer → up to 3 plans<br/>Cheapest now · Max savings · Fastest"]
  F --> G["Compare plans: net, savings vs baseline,<br/>orders, pending shortfalls, reasons"]
  G --> H{"Tweak?"}
  H -- "lock item to platform /<br/>don't split / change need-by" --> E
  H -- accept --> I["Baskets created<br/>ready + pending"]
  I --> J["For each ready basket:<br/>open platform (deep link), add items, checkout"]
  J --> K["Mark placed → enter amount paid"]
  K --> L["Ledger: paid, cashback expected"]
  I --> M["Pending baskets → see §4/§5"]
```

**UX notes**
- The plan screen leads with **one number**: "₹1,239 total · save ₹50 vs one order". Details expand from there.
- Each order card shows `₹674 / ₹500 ✓ ₹50 cashback` or `₹344 / ₹500 · ₹156 short ⏳`.
- The checkout helper shows a checklist of items with pack sizes, so the person checking out doesn't buy the wrong 1 kg vs 5 kg.

## 2. Wishlist watch → alert → basket

```mermaid
sequenceDiagram
  actor U as User
  participant W as PWA
  participant API
  participant J as scan_watches job
  participant N as Notifier
  U->>W: Watch "Almonds 1kg" ≤ ₹600 net OR ≥ 45% off
  W->>API: POST /watches
  loop every refresh
    J->>API: latest prices for watched products
    J->>J: evaluate rule (ANY/ALL), membership-aware landed price
    alt hit and not in cooldown and not quiet hours
      J->>N: notify(dedupe_key)
      N-->>U: "Almonds ₹590 on Amazon (−49%). Completes your pending Amazon basket (₹70 short)."
    end
  end
  U->>W: Tap alert
  W->>API: add need → offer "Add to pending Amazon basket"
  API-->>W: basket now ₹520 / ₹500 → READY
```

Matching rule: a watch on a **product** matches only that product's listings. A watch on a **generic need**
("almonds 1 kg, any brand") matches products in that category whose pack is within ±20% and whose unit rate is compared.
No keyword "any word matches" logic (prototype bug, see CODE_ANALYSIS §4).

**Built so far (staples tracker):** a watch is a `listing_watch` row on one listing, with an optional target (`PUT /listings/{id}/watch`).
`GET /deals/feed` lists watched or custom listings that are in stock with a fresh/ok, non-sample price and at least one reason:
`below_target`, `low_30d` (≥ 3 observations in 30 days, the price has moved, and it's at the low) or `under_avg` (≥ 15% under the 30-day
average, integer maths). The web shows it as the **Deals** tab. Adding a product: paste a link → `POST /listings/autofill` reads the
Amazon/Flipkart page once (10 s apart from any other fetch), fills brand/pack/family by rules and, only if something is still missing,
one capped Gemini call → the user confirms and saves. Quick-commerce links are never fetched.

**Catalog → Find on shops:** "Add an item…" on the Plan page also searches `catalog_product`. A catalog need shows **Find on shops**: the
server builds 5 shop search URLs (`GET /catalog/{id}/search-urls`); the extension opens each one in a background tab (only those 5 search
shapes, only for a request from the DealScour origin, one search at a time, ≥ 3 s apart, 20 s timeout), reads up to 5 product links per shop
and closes the tab. `POST /catalog/{id}/candidates` drops non-product links and sorts by brand/pack/name words for display only. The owner ticks
the right ones → normal `POST /listings`. Nothing is tracked without the tick.

**Deal radar (ADR-026):** Telegram Web tab → extension reads only listed channels → `POST /radar/posts` (extension token) stores them
`pending` → every 60 s the radar loop resolves links, drops posts that match no keyword or tracked family (post text + URL slug) without
fetching, checks the live price for the rest, and decides `good`/`expired`/`not_relevant`/… → a good one becomes a `radar_alert`: Telegram
message from the owner's bot (held in quiet hours, India time) and a Chrome notification (the extension polls `/radar/alerts` every 2 min).
The Radar page lists channels, keywords and the last 50 posts with their verdicts. Deals shows a "From Telegram" section.

## 3. Optimizer request (system sequence)

```mermaid
sequenceDiagram
  participant W as PWA
  participant API
  participant DB
  participant P as pricing
  participant O as optimizer (pure)
  W->>API: POST /plans {list_ids, settings}
  API->>DB: needs, products, listings, latest prices, offers (uses_left), fee schedules, memberships, restock, watches, open pending baskets
  API->>P: landed line prices per candidate (membership + item coupons), unit rates, freshness
  API->>API: build filler pool (restock due, watches near target, non-urgent needs)
  API->>O: plan(PlanRequest)
  O->>O: baseline · CP-SAT (≤1s) → fallback heuristic · 3 labelled plans · reasons
  O-->>API: PlanSet
  API->>DB: persist plan (request + result) for audit/replay
  API-->>W: PlanSet
```

Replays: any stored plan can be re-run from `request_json`. This is how bugs are reported and turned into golden tests.

## 4. Pending basket lifecycle

```mermaid
stateDiagram-v2
  [*] --> Draft: plan accepted / manual basket
  Draft --> Ready: subtotal ≥ target threshold
  Draft --> Pending: below threshold, user chose to hold
  Pending --> Ready: items/fillers added, or pooled
  Ready --> Pending: item removed / price rose below threshold
  Pending --> Rehomed: cheaper to complete elsewhere (user accepts)
  Rehomed --> Draft: new basket on other platform
  Pending --> Released: deadline hit → user chooses "place without offer"
  Released --> Ready: offer dropped, threshold = none
  Pending --> Expired: deadline passed, no action
  Expired --> Draft: items return to list as open needs
  Ready --> Placed: user marks placed (actual paid)
  Placed --> Settled: cashback received / not applicable
  Placed --> CashbackMissed: window elapsed without cashback
  CashbackMissed --> Settled: marked resolved
  Settled --> [*]
```

**Nudges**
- On entering `Ready`: "Your Amazon basket is ₹515. Place it to get ₹50."
- `Pending` at T-48 h and T-12 h before the deadline: "₹120 short. Top fillers: Vim Gel ₹199 (due), Tata Tea ₹240 (on list)."
- Price drop on an item already in a pending basket: no alert unless it changes `Ready`/`Pending` status.

## 5. Filling a pending basket

```mermaid
flowchart TD
  A["Pending Amazon basket ₹344 / ₹500<br/>short ₹156 · deadline 28 Oct"] --> B["Build filler pool"]
  B --> B1["Restock due ≤ deadline + 7d"]
  B --> B2["Watches within 5% of target"]
  B --> B3["Non-urgent needs on other lists<br/>(≤ ₹10 worse than their best platform)"]
  B1 & B2 & B3 --> C["Score: on-list +3 · restock +2 · non-perishable +2 ·<br/>near-target +1 · −overshoot · −perishable"]
  C --> D["Show top 5 combos that cover ₹156<br/>with least overshoot"]
  D --> E{"User picks"}
  E -- "add Vim Gel ₹199" --> F["₹543 ✓ → Ready"]
  E -- "nothing fits" --> G{"Options"}
  G --> G1["Pool with household/circle basket (§7)"]
  G --> G2["Re-home items to another platform"]
  G --> G3["Place without offer"]
  G --> G4["Wait (keep pending)"]
```

Combos are found with a small subset-sum over the pool (≤ 30 candidates). The search minimises overshoot, then maximises score.

## 6. Offer Wallet: add, use, expire

```mermaid
flowchart LR
  A["See offer in app/SMS/email"] --> B["Add offer: pick template<br/>Flat ≥X · %≤cap · Tiered · Bank · Free delivery · Item · Multi-buy"]
  B --> C["Fill: platform account, min order,<br/>value, uses, valid till, payment method, stack group"]
  C --> D["Visibility: private / household / circle"]
  D --> E[("Offer instance<br/>uses_left = n")]
  E --> F["Optimizer uses it in plans"]
  F --> G["Basket placed → uses_left −1<br/>cashback expected"]
  E --> H["offer_expiry job: T-2d reminder<br/>(only if a plan or pending basket could use it)"]
  H --> I["Expired → archived"]
```

Shared offers: when a circle member shares "Amazon ₹50 on ₹500", others get a **"Do you have this too?"** prompt.
Confirming creates *their own* instance on *their own* account. Uses are never shared.

## 7. Household & circle: share, pool, settle up

```mermaid
sequenceDiagram
  actor A as Deepak (Household 1)
  actor B as Sister (Household 2, same building)
  participant API
  A->>API: Pending Amazon basket ₹340 (short ₹160)
  B->>API: Pending Amazon basket ₹210 (short ₹290)
  API-->>A: "Pool with Sister? Combined ₹550 ✓ unlocks ₹50 (1 use from your account)"
  A->>API: POST /baskets/{a}/pool {other: b}
  API-->>B: approve pooling?
  B->>API: approve
  API->>API: merged basket on A's account · lines keep owner_household_id
  A->>API: placed, paid ₹550
  API->>API: ledger: B owes A ₹210 − share of cashback (₹50 × 210/550 ≈ ₹19) = ₹191
  API-->>B: "You owe Deepak ₹191"
```

Rules
- Pooling only happens across a **shared delivery address** or with an explicit "I'll hand it over" confirmation.
- Cashback is split pro rata by line value by default. The option is configurable to "orderer keeps cashback".
- Settle-up is a ledger entry and a UPI deep link (`upi://pay?...`). The app never moves money.

## 8. Price refresh & freshness

```mermaid
flowchart TD
  S["Job: refresh_prices"] --> Q["Select listings: watched ∪ in open baskets ∪ on open lists"]
  Q --> R{"Adapter enabled<br/>for platform?"}
  R -- no --> X["Skip; prices age → stale badge"]
  R -- yes --> T["Rate-limited fetch (≤1 req/10s, jitter)"]
  T --> U{"OK?"}
  U -- yes --> V["Insert PriceObservation(source, observed_at)"]
  U -- "fail ×3" --> W["Disable adapter, notify owner"]
  V --> Y["Trigger scan_watches + check_pending"]
  M["Manual / link / extension capture"] --> V
```

**Browser extension (optional, ADR-025).** Plans → "Check live prices and plan" sends the list's product links to the extension. It opens each one in a
background tab (≤ 15 per run, ≥ 8 s apart per shop), reads the price only from Amazon's price block or the page's JSON-LD, and posts it to
`POST /prices/capture` (`source = "extension"`). A price more than 60% off the last one is listed under "Check these prices" for the user to
confirm or skip; the rest carry on. "Add to cart" on a ready basket opens the extension's confirmation window; after "Add N items" it opens each
product page, clicks add-to-cart once if the page is that product, and leaves the last tab on the shop for the human to check out.

## 9. Post-order reconciliation & savings ledger

```mermaid
flowchart LR
  A["Mark placed"] --> B["Enter actual paid (prefilled from plan)"]
  B --> C{"Differs from plan > ₹10?"}
  C -- yes --> C1["Ask what changed: price / OOS / offer not applied"] --> D
  C -- no --> D["Ledger: paid · cashback expected (due by date)"]
  D --> E["Needs → bought · restock last_bought_on updated · cadence re-learned"]
  D --> F{"Cashback received by due date?"}
  F -- yes --> G["Mark received → savings confirmed"]
  F -- no --> H["Reminder → mark missed → lower confidence ρ for that offer type"]
```

Dashboard: **This month**: MRP ₹8,420 · paid ₹6,910 · offers captured ₹410 · cashback pending ₹100 · vs naïve plan +₹230.

## 10. Screen map

```mermaid
flowchart TD
  Home["Home<br/>pending baskets · alerts · this month's savings"] --> List["Lists<br/>quick add · need-by · flex"]
  Home --> Plans["Plan<br/>3 plans · orders · reasons · lock/tweak"]
  Home --> Baskets["Baskets<br/>ready · pending (shortfall bar) · placed"]
  Home --> Deals["Deals<br/>grid · compare modal · unit-rate matrix"]
  Home --> Wallet["Offer Wallet<br/>active · expiring · shared"]
  Home --> Watch["Wishlist<br/>watches · hit history"]
  Home --> Ledger["Savings ledger"]
  Home --> Settings["Settings<br/>accounts & memberships · fee schedules · household/circle · alerts · adapters"]
  List --> Plans --> Baskets
  Baskets --> Fillers["Fillers sheet"]
  Deals --> Watch
  Deals --> List
```

The prototype's tabs map as follows: *Deals* → Deals, *Matrix* → Deals ▸ Compare, *Cart* → Plans/Baskets (rebuilt),
*Alerts* → Wishlist, *Architecture* → removed (dev docs live in `docs/`).
