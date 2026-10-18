# DealScour 🧺

**Smart grocery baskets for you, your family and friends.** It plans the *smallest set of orders* across Amazon, Flipkart,
Blinkit, Swiggy Instamart and Zepto that captures the *most offer value* for things you actually need.

> Amazon gives ₹50 cashback on ₹500. Your list is ₹1,000.
> DealScour splits it into **two ₹500 orders** (₹100 back, not ₹50). When the second order is ₹150 short, it becomes a
> **pending basket** that fills with things you'd buy anyway.

## What it does
- **Quick lists**: type `atta 5kg, oil 5L, ghee 1L` and it understands. Mark lines *any brand* or *no rush*.
- **Offer Wallet**: record the offers you hold (flat cashback, % with cap, tiered, bank card, free delivery…) with uses left.
- **Basket optimizer**: up to 3 plans (*Cheapest now*, *Max savings*, *Fastest*) with plain-English reasons.
- **Pending baskets**: shortfall, deadline, and filler suggestions from your restock list and wishlist.
- **Wishlist alerts**: target price or unit rate, delivered by Telegram or push notification.
- **Membership-aware prices**: Prime, Swiggy One, Flipkart Plus, Zomato Gold and Zepto Pass are applied correctly, with fees per order.
- **Family & friends**: shared lists, shared deal feed, pooled baskets with a settle-up ledger.
- **Savings ledger**: what you paid, offers captured, cashback still pending.

## Status
🚧 **Phase 0 (foundation) in progress.** `backend/` has the FastAPI skeleton; the original prototype lives in `prototype/`:

| File | |
|---|---|
| `prototype/dealscour_v3.html` | UI prototype (open in a browser) |
| `prototype/deal_scour_backend.py` | Mock pricing + wishlist scan (`python3 prototype/deal_scour_backend.py`) |

## Docs
| Doc | Read it for |
|---|---|
| [docs/PRD.md](docs/PRD.md) | Features, users, glossary, scope |
| [docs/BASKET_OPTIMIZER.md](docs/BASKET_OPTIMIZER.md) | The algorithm, every offer combination, worked examples |
| [docs/FLOW.md](docs/FLOW.md) | User and system flows (Mermaid) |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Components, repo layout, data model, API, jobs |
| [docs/DECISIONS.md](docs/DECISIONS.md) | ADRs: why it's built this way |
| [docs/CODE_ANALYSIS.md](docs/CODE_ANALYSIS.md) | Prototype breakdown and bugs not to port |
| [docs/ROADMAP.md](docs/ROADMAP.md) | Phases and exit criteria |
| [AGENTS.md](AGENTS.md) / [CLAUDE.md](CLAUDE.md) | Instructions for AI coding agents |

## Stack (planned)
Python 3.11 · FastAPI · SQLite · OR-Tools CP-SAT · APScheduler · React + TypeScript PWA · Telegram bot · Docker Compose + Caddy.

## Principles
Personal and free to run · no auto-checkout, no stored passwords · every price shows where and when it came from ·
the optimizer explains itself · no junk fillers.
