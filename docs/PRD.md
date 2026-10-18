# DealScour — Product Requirements

*Status: Draft v1 · 2026-10-18 · Owner: Deepak*

## 1. Problem

Indian grocery shopping is spread across five apps. Each app has its own memberships, fee schedules and
**threshold offers** ("₹50 cashback on ₹500", "10% off up to ₹100 with HDFC, min ₹750", "free delivery above ₹199").
The cheapest *item* price is often not the cheapest *outcome*. What you actually pay depends on:

- **how you split the shopping into orders.** One ₹1,000 order earns ₹50. Two ₹500 orders earn ₹100.
- **which orders can wait.** A ₹350 order can be held until you have ₹150 more of things you'd buy anyway.
- **which memberships and payment methods you hold**, and how many uses of each offer you have left.
- **urgency.** Milk is needed today. Atta can wait 10 days.

Nobody works this out by hand every week. The result is money left on the table, or worse, junk bought
just to hit a threshold.

## 2. Vision

> **The smallest set of baskets that captures the most offer value, for the things you actually need.**

DealScour is a personal tool for me, my family and friends. It is self-hosted and costs nothing to run, with no
ads and no affiliate bias.

## 3. Users

| Persona | Who | Primary job |
|---|---|---|
| **Planner** (me) | Runs the household's monthly shop, holds most memberships | Build optimal baskets, track pending ones, see savings |
| **Household member** (spouse, parents) | Adds things as they run out | "Add milk, Surf Excel" in 3 seconds from a phone |
| **Friend / relative** (another household) | Separate address and accounts | Gets shared deal alerts, occasionally pools a basket |

## 4. Core concepts (glossary)

| Term | Meaning |
|---|---|
| **Need** | Something you want to buy: "Atta 5 kg", optionally brand-flexible or pack-flexible, with a *need-by* date. |
| **Product** | Canonical item: *Aashirvaad Select Atta, 5 kg*. |
| **Listing** | A product on a platform at a pincode, with a URL. |
| **Price observation** | Price, MRP, member price, stock and ETA for a listing at a point in time, with its source. |
| **Landed price** | What an item really costs *inside a specific order*, after item coupons. Order fees are added at order level. |
| **Unit rate** | Landed price per kg, per L or per 100 g. Used to compare pack sizes. |
| **Offer** | A structured rule held by a specific platform account: threshold cashback, % with cap, tiered, bank card, free delivery, multi-buy… |
| **Offer slot** | One remaining *use* of an offer. "₹50 on ₹500, 2 uses/month left" = 2 slots. |
| **Order** | One checkout on one platform. Has subtotal, fees and offers applied. |
| **Plan** | A set of orders covering your needs, with total cost, savings and an explanation. The optimizer returns 2–3 alternative plans. |
| **Pending basket** | An order that is deliberately *not placed yet*, because it is short of an offer threshold. Has a shortfall, a deadline and filler suggestions. |
| **Filler** | An item you'd buy anyway (restock due soon, wishlist near target, a non-urgent need) that is used to close a shortfall. |
| **Dead weight** | Spend above an offer threshold that could have unlocked another slot. "₹480 over threshold. Split to earn ₹50 more." |
| **Watch** (wishlist) | "Tell me when X ≤ ₹Y net, or ≥ Z% off." |
| **Restock item** | A staple with a cadence ("Atta every ~30 days"). It feeds predicted needs and fillers. |
| **Household** | People sharing an address, lists and baskets. |
| **Circle** | A group of households (friends and family) that share a deal feed and can pool baskets. |

## 5. Features

Priority: **M** = MVP, **S** = soon after, **L** = later.

### 5.1 Capturing needs
- **M** Quick list: type `atta 5kg, oil 5L, ghee 1L, surf 2L`. It is parsed into needs with qty and pack size. Fuzzy matching to products. Each line can be ticked "any brand" or "any pack size".
- **M** Multiple lists: *This week*, *Monthly*, *Party on Saturday*. Each line has a need-by date (today / this week / no rush).
- **M** One-tap add from deals, wishlist hits and restock reminders.
- **S** Share-sheet / Telegram bot add: `/add milk 2L`.
- **S** Restock cadences that are learned from placed orders. "You buy Atta every 28 days, so it's due in 4 days."
- **L** Optional LLM parsing for messy lines ("the green Surf one, big") — ADR-016.

### 5.2 Prices & deals
- **M** Manual price entry and **paste a product link**. The app parses platform, product and pack from the URL or page.
- **M** Deal grid: per product, compare across platforms by landed price and unit rate, with membership effects.
  This is the prototype's main tab, done correctly.
- **M** Freshness badges ("seen 2 h ago by Amma", "stale: 3 days").
- **S** Browser extension that records the prices you see while browsing normally (ADR-004).
- **S** Opt-in, rate-limited fetchers per platform for watched items only.
- **L** Price history sparkline and "is this actually a good price?" (vs 90-day median).

### 5.3 Offer Wallet
- **M** Add an offer in under 20 s using templates: *Flat cashback ≥ X*, *% off up to cap ≥ X*, *Tiered*, *Bank card*, *Free delivery ≥ X*, *Item coupon*, *Multi-buy*.
- **M** Validity, uses left, owner account, payment method required, stackable-with group, and value type (cash / Amazon Pay / SuperCoins), each with a valuation multiplier.
- **M** Expiry reminders ("₹50 Amazon offer expires Sunday. You have a pending basket short ₹120").
- **S** Share an offer to household or circle. Others see it but **use their own account's** instance.

### 5.4 Basket optimizer (the core)
- **M** "Plan my list" returns **up to 3 plans**:
  1. **Cheapest now**: everything placed today.
  2. **Max savings**: may include pending baskets, with shortfall and deadline shown.
  3. **Fastest**: respects need-by dates, using quick commerce where it's worth it.
- **M** Each plan shows its orders by platform, the subtotal against the threshold, fees, offer value, net total, savings vs baseline,
  and **plain-English reasons** ("Ghee moved to Instamart: ₹20 cheaper and gets you over free delivery").
- **M** Dead-weight hints and "add ₹X to unlock ₹Y" hints.
- **M** Lock controls: "keep this item on Amazon" or "don't split this order". Re-plan instantly.
- **S** Pack-size arbitrage (2 × 500 g vs 1 kg), and brand substitution within a flexible need.
- See `BASKET_OPTIMIZER.md` for the full model and offer combinations.

### 5.5 Pending baskets
- **M** First-class list of pending baskets showing platform, current subtotal, threshold, **shortfall**, offer at stake, deadline
  (offer expiry or earliest need-by date of its items), and a progress bar.
- **M** **Filler suggestions** ranked by "regret-free score": non-perishable, already on a list or due for restock, smallest overshoot.
- **M** Adding any need for that platform from anywhere offers "Add to pending Amazon basket (₹70 short → ✓)".
- **M** Auto-nudge when ready ("Pending Amazon basket now ₹515. Place it.") or near the deadline, with three choices:
  *add fillers* / *place without offer* / *move items elsewhere*.
- **S** **Pool with household or circle**: another member's pending basket on the same platform and address is merged.
  A settle-up ledger tracks who owes whom.

### 5.6 Wishlist & alerts
- **M** Watch a product or a flexible need with target net price, **or** target unit rate, **or** min % off. The rule is ANY or ALL (the prototype hard-coded OR).
- **M** A scheduled scan re-evaluates watches as prices update.
- **M** Alerts via Web Push (PWA) and Telegram. They have dedupe, cooldown and quiet hours (22:00–07:00).
- **S** Alerts know about baskets: "Almonds hit ₹590. Adding them completes your pending Amazon basket."

### 5.7 Orders & savings ledger
- **M** "Mark as placed": confirm the actual amount paid, and optionally attach a screenshot. Cashback stays *expected* until marked *received*.
- **M** Savings dashboard: this month's MRP vs paid, offer value captured, cashback still pending, top wins.
- **S** Reminders for cashback not received within its expected window.

### 5.8 People & sharing
- **M** Single household, invite-only.
- **S** Multiple households and circles, with roles (owner / member / viewer) and a shared deal feed.
- Memberships and offers belong to **platform accounts**, which belong to a person. The optimizer only uses
  accounts the household can order from.

## 6. Non-goals
- Auto-checkout, storing platform credentials, or acting on a user's platform account (ADR-020).
- A public website, SEO pages, affiliate monetisation.
- Exhaustive catalog coverage. We care about the ~100–300 SKUs a household actually buys.
- Real-time inventory of every dark store.

## 7. Success metrics (personal scale)
- **Offer capture rate**: offer value captured ÷ offer value available on placed orders. Target ≥ 85%.
- **Savings vs naïve**: net paid vs "single cheapest-platform order" baseline. Target ≥ 8% per month.
- **Filler regret**: fillers later marked "didn't need". Target < 5%.
- **Time to plan**: list typed to plan shown in under 60 s, with optimizer p95 under 1.5 s.
- **Family adoption**: at least 3 people add items in a typical week.

## 8. Platforms (initial)

| Platform | Type | Typical membership | Notes |
|---|---|---|---|
| Amazon India | Next-day / Fresh | Prime | Threshold cashback (Amazon Pay), bank offers, Subscribe & Save, clip coupons |
| Flipkart Grocery / Minutes | Next-day / quick | Flipkart Plus / VIP | SuperCoins, bank offers, tiered "₹X off on ₹Y" |
| Blinkit | Quick (10–15 min) | Zomato Gold | Free-delivery threshold, handling, small-cart and surge/rain fees |
| Swiggy Instamart | Quick | Swiggy One | Free delivery above threshold for members, member markdowns |
| Zepto | Quick | Zepto Pass | Pass prices, free-delivery threshold, platform fee |

Fee and offer numbers in the prototype are **samples**. Real terms change often and must come from the
Offer Wallet and the per-platform fee schedules that the user can edit in Settings.
