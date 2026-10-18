# Roadmap

*Personal project, evenings and weekends. The phases are sized so each one is useful on its own.*

## Phase 0: Foundation (≈ 1 week)
- [x] `git init`, move prototype files → `prototype/` (ADR-018), and strip nothing.
- [ ] Scaffold `backend/` (venv+pip, FastAPI, SQLModel, Alembic, ruff, mypy, pytest) and `web/` (Vite, React, TS, Tailwind, PWA plugin).
- [ ] `core/money.py` (paise helpers), `pricing/units.py`, `pricing/fee_schedules.py`, `pricing/landed.py` with tests.
- [x] Seed file with the 28 prototype listings as `source="sample"` (walnuts get their own product) → `backend/app/seed/prototype_catalog.json`.
- [ ] `docker-compose.yml` + Caddy, running locally.

**Exit:** `GET /deals` returns correct membership-aware landed prices and unit rates, with order-level fees shown separately.

## Phase 1: MVP: lists, offers, optimizer, pending baskets (≈ 3 weeks)
- [ ] Auth (email OTP, invite link), single household.
- [ ] Lists + quick-add parser (rule-based) + product matching with confirmation.
- [ ] Manual price entry and paste-a-link listing creation. Freshness badges.
- [ ] Offer Wallet: templates for kinds 1–7 (`BASKET_OPTIMIZER.md` §3).
- [ ] Optimizer: contract, baseline, heuristic, CP-SAT model, explanations. **Golden tests Ex 1–7**, plus property tests.
- [ ] Plans screen (3 plans, reasons, lock/tweak), accept → baskets.
- [ ] Baskets screen: ready / pending with shortfall bar, fillers sheet, place and reconcile.
- [ ] Deals grid + compare modal (ported UX).

**Exit:** I plan a real monthly shop with it and capture the ₹50 + ₹50 split.

## Phase 2: Watches, alerts, restock, ledger (≈ 2 weeks)
- [ ] Watches (ANY/ALL, unit-rate targets), APScheduler jobs, `job_run` locks.
- [ ] Web Push + Telegram bot (`/add`, `/list`, `/pending`), quiet hours, dedupe.
- [ ] Restock cadences (manual, then learned from placed baskets). Filler pool v1.
- [ ] Pending basket nudges (ready, T-48 h, T-12 h), offer expiry reminders.
- [ ] Savings ledger + monthly dashboard. Cashback received/missed tracking.

**Exit:** The family adds items from their phones. Alerts are correct with zero false hits.

## Phase 3: Better price data (≈ 2–3 weeks)
- [ ] Browser extension (MV3) capturing prices on platform pages you're viewing → `/prices/capture`.
- [ ] Optional Amazon PA-API adapter (if Associates eligibility is met).
- [ ] Optional per-platform fetchers for watched items (rate-limited, off by default, auto-disable).
- [ ] Price history sparkline, 30/90-day low, "good price?" badge.
- [ ] Offer kinds 8–14 (multi-buy, S&S, category/brand-restricted, time windows).

## Phase 4: Friends & family (≈ 2 weeks)
- [ ] Multiple households, circles, roles.
- [ ] Shared deal feed and "Do you have this offer too?" prompts.
- [ ] Pooled baskets with approval, pro-rata cashback split, and settle-up ledger with UPI deep links.
- [ ] Per-person data export and delete.

## Phase 5: Smart extras (as desired)
- [ ] Optional LLM parsing for messy list lines (ADR-016), with a spend cap.
- [ ] Pack-size arbitrage and brand substitution suggestions.
- [ ] "Best time to buy" from price history (e.g. sale-event patterns).
- [ ] Monthly budget per household with plan-time warnings.

## Risks & mitigations
| Risk | Mitigation |
|---|---|
| Price data is stale or laborious to enter | Family crowd-sourcing, link paste, extension capture. Freshness is always visible |
| Platforms change offer mechanics | Offer kinds are data plus small model pieces. Fee schedules are user-editable |
| Pending baskets never complete | Deadlines, nudges, ρ discount, and the "place without offer" option |
| Filler creep (buying junk) | Fillers come only from lists, restock and watches. Regret tracking |
| Fetchers break or violate terms | Opt-in, watched-only, rate-limited, auto-disable. App fully works without them |
