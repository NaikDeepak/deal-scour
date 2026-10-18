# AGENTS.md — Guide for AI coding agents

> Canonical instructions for any AI agent (Claude Code, Codex, Cursor, Qodo…) working in this repo.
> `CLAUDE.md` imports this file — edit rules **here**, not there.

## 1. What this project is

**DealScour** is a *personal* (self + friends & family) grocery deal planner for India.
It does not try to be a price-comparison website. Its job is to answer one question:

> "Given what I need, the offers I hold and the memberships I pay for, **how should I split my
> shopping into orders** so that I pay the least, without buying junk to hit thresholds?"

Example: Amazon gives ₹50 cashback on orders ≥ ₹500. A ₹1,000 basket placed as one order earns ₹50.
Placed as two ₹500 orders, it earns ₹100. When the second order is ₹150 short, it becomes a
**pending basket** that waits for items you were going to buy anyway.

Platforms in scope: Amazon India, Flipkart (Grocery/Minutes), Blinkit, Swiggy Instamart, Zepto.
Home pincode: 411018 (Pimpri-Chinchwad). The design supports multiple households and pincodes.

## 2. Repo status (read this first)

| Path | State |
|---|---|
| `dealscour_v3.html` | **Prototype / reference only.** Single-file Tailwind UI with mocked data. Do not extend it. |
| `deal_scour_backend.py` | **Prototype / reference only.** Mock catalog + wishlist scan. Do not extend it. |
| `docs/` | Source of truth for product, architecture, flows, decisions. |
| `backend/`, `web/` | **Not yet scaffolded.** Target layout is in `docs/ARCHITECTURE.md` §3. |

⚠️ **`dealscour_v3.html` line 136 is an ~870 KB base64 JPEG.** Never `cat` or fully read the file.
Use `grep -n` / `sed -n 'A,Bp' | cut -c1-200`. JS lives at lines ~972–2691.

## 3. Read order

1. `docs/PRD.md`: what we're building and for whom
2. `docs/BASKET_OPTIMIZER.md`: the core algorithm (the product's main value)
3. `docs/ARCHITECTURE.md`: components, data model, API
4. `docs/FLOW.md`: user flows and system flows
5. `docs/DECISIONS.md`: why things are the way they are (ADRs). **Check before changing a convention.**
6. `docs/CODE_ANALYSIS.md`: what the prototype does and which bugs not to port
7. `docs/ROADMAP.md`: what to build next

## 4. Non-negotiable invariants

These come from ADRs. Breaking one needs a new ADR in `docs/DECISIONS.md`.

1. **Money is integer paise** (`int`, ₹1 = 100). No floats for money anywhere: DB, API or optimizer. (ADR-009)
2. **Fees are order-level, never item-level.** Delivery, handling, small-cart, platform and surge fees attach
   to an *order*, as a function of its subtotal. The prototype's per-item delivery fee is a bug. (ADR-011)
3. **The optimizer is a pure function.** `plan(request) -> PlanSet`. No DB, network or clock access inside.
   It is deterministic for a given input. Every plan carries a human-readable explanation. (ADR-006)
4. **The optimizer runs server-side only.** It has one implementation. The web app never re-implements pricing
   or optimization logic. The prototype duplicated it in Python and JS, and the two drifted. (ADR-019)
5. **Never place orders or store platform passwords/cookies.** The app plans and deep-links. The human checks out. (ADR-020)
6. **Every price has provenance:** `source`, `observed_at`, `pincode`. Stale prices are flagged in the UI and
   down-weighted by the optimizer. Never show a stale price as if it were live. (ADR-004)
7. **Offers are user-entered structured rules** (the Offer Wallet). They are not scraped. Usage limits are per platform
   account, not per household. (ADR-005)
8. **Scrapers are opt-in, rate-limited, personal-use only.** They don't log in, solve CAPTCHAs or rotate proxies. A disabled adapter
   must not break anything. (ADR-004)
9. **Matching never falls back to "first item in catalog".** The prototype's `|| DEALS_DATABASE[0]` produced false
   "TARGET HIT" alerts. No confident match means *no match*.
10. **Escape all user/scraped text** before rendering. Use framework rendering. No `innerHTML` built from strings.

## 5. Conventions

### Backend (Python 3.11+, FastAPI)
- Layout: `backend/app/{api,core,domain,pricing,optimizer,sources,matching,jobs,notify}`.
- Pydantic v2 models at API edges. SQLModel/SQLAlchemy 2.0 for persistence. Alembic for migrations (never edit an applied migration).
- Type hints are required. `ruff` + `mypy --strict` for `optimizer/` and `pricing/`.
- Use async for I/O-bound code (adapters, notifications). The optimizer is sync and CPU-bound, so run it in a threadpool.
- Name things in domain language: `Need`, `Product`, `Listing`, `PriceObservation`, `Offer`, `Order`,
  `Basket`, `PendingBasket`, `Plan`, `Filler`. Don't use `item`/`data`/`obj`.

### Web (React + TypeScript + Vite, installable PWA)
- Layout: `web/src/features/{list,wishlist,baskets,offers,deals,household,settings}`.
- Server state goes through TanStack Query. No business logic in components: display what the API returns.
- Format paise with one helper (`formatINR(paise)`). Never divide by 100 inline.
- Mobile-first. Family members will use this on phones in a store aisle.

### Tests
- `backend/tests/optimizer/` holds **golden tests**. Every worked example in `docs/BASKET_OPTIMIZER.md` §6 must exist
  as a test with the exact expected rupee figures. If you change the optimizer, these must still pass, or the doc must be updated
  in the same change with justification.
- Property tests (Hypothesis): a plan never costs more than the "single cheapest order per platform" baseline,
  and never uses an offer more times than `uses_left`.
- Adapters are tested against saved HTML/JSON fixtures in `backend/tests/fixtures/`. Tests never hit the live network.

## 6. Commands (once scaffolded)

```bash
# backend (plain venv + pip; uv is not required)
cd backend && python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/uvicorn app.main:app --reload
.venv/bin/pytest -q                  # all tests
.venv/bin/pytest tests/optimizer -q  # golden + property tests
.venv/bin/ruff check . && .venv/bin/mypy app/optimizer app/pricing
.venv/bin/alembic upgrade head

# web
cd web && pnpm i && pnpm dev
pnpm test && pnpm lint && pnpm typecheck

# everything
docker compose up --build
```

Prototype only: `python3 deal_scour_backend.py`, or open `dealscour_v3.html` in a browser.

## 7. Task playbooks

### Add a new platform (e.g. BigBasket, JioMart)
1. Add the enum value to `domain/platform.py` with its fee schedule defaults (`pricing/fee_schedules.py`).
2. Implement `sources/<platform>.py` against `SourceAdapter` (see ARCHITECTURE §5). Start with `link_parse` only.
3. Add fixtures and adapter tests. Register the adapter behind a feature flag, default **off**.
4. Add the brand colour and badge in `web/src/features/deals/platformMeta.ts`.
5. Update `docs/PRD.md` platform list.

### Add a new offer kind (e.g. "Buy 2 get 1")
1. Add the kind to `domain/offer.py` with a typed params model and validation.
2. Model it in `optimizer/model.py` (CP-SAT) **and** `optimizer/heuristic.py` (fallback). The two must agree on small cases.
   Add a cross-check test.
3. Add an explanation template in `optimizer/explain.py`.
4. Add a golden test plus a row to the offer-kind table in `docs/BASKET_OPTIMIZER.md` §3.
5. Add an entry form in `web/src/features/offers/`.

### Change optimizer behaviour
- Write an ADR if the objective or tie-breaking changes.
- Update the golden tests and the worked examples in the same PR.

### Add a notification channel
- Implement `notify/<channel>.py` against `Notifier`. It must respect quiet hours, dedupe keys and per-user opt-in.

## 8. Definition of done
- Tests pass, lint and type checks are clean, new behaviour is covered.
- Docs are updated: a flow changed → `FLOW.md`; a decision made → `DECISIONS.md`; schema changed → `ARCHITECTURE.md` §4.
- No secrets in code. Config comes from `.env` (see `.env.example`).
- UI checked at 360px width and in dark mode.

## 9. Things agents should NOT do
- Don't extend the prototype files. Port ideas into `backend/` and `web/`.
- Don't add a scraper that needs login, cookies or CAPTCHA solving.
- Don't add paid infrastructure (WhatsApp Business API, managed Postgres, etc.) without an ADR. This is a
  zero-to-low-cost personal project.
- Don't invent offer terms or prices in seed data without marking them `source="sample"`.
- Don't commit to `main`, push, or open PRs unless you are the lead. Builders commit on their own branch only
  (see "Working with other agents" below).

# Working with other agents (shared notepad)

<!-- agent-notepad protocol. Copy this section into your repo's AGENTS.md (Codex and Antigravity read AGENTS.md
     natively; point CLAUDE.md / GEMINI.md at it). Replace the names below with yours. -->

Several coding agents may work on this repo at the same time:

| Name | Who | Role |
|---|---|---|
| `claude` | Claude Code | **Lead.** Plans, writes task specs, assigns work, reviews, merges. Deploys only when the human asks. |
| `agy` | Antigravity CLI | Builder. Works only on a task the lead (or the human) assigned, on the branch named in the task. |
| `codex` | OpenAI Codex CLI | Reviewer / auditor. Read-only unless the task says otherwise. |
| `human` | You, the owner | Decides priorities, approves merges to production, owns secrets. |

Everyone coordinates through an append-only notepad, `.collab/notepad.md` (gitignored, local only).
**Always use `scripts/collab.sh`; never edit the notepad by hand.**

```bash
scripts/collab.sh status                          # active claims + latest entry for each agent
scripts/collab.sh read 30                         # last 30 entries
scripts/collab.sh claim <me> "<branch> · <files/area>"
scripts/collab.sh post <me> <claude|agy|codex|human|all> "<message>"
scripts/collab.sh handoff <me> <other> "<branch> · <done> · <next>"
scripts/collab.sh release <me> "<note>"
scripts/collab.sh cost                            # tokens and cost per agent and model
```

## Protocol
1. **Start of every task:** run `scripts/collab.sh status` and read anything addressed to you or to `all`.
2. **Claim before editing.** One claim per agent (a new claim replaces your previous one). Name the branch and the files or area.
3. **Never edit files, or push to a branch, that another agent has claimed.** Ask with `post` instead.
4. **Separate branches, ideally separate worktrees.** Never commit to `main` directly; changes go through a PR.
5. **Stay inside the task spec.** Touch only the files it lists. If you need more, `post` to the lead and wait.
6. **Ask, don't block silently.** Questions to the lead or the human go through `post`.
7. **Finishing or pausing:** write a `handoff` (branch, what's done, what's next, test result), then `release`.
   The lead records every agent's model and token usage from the CLIs' own logs; don't post usage yourself.
8. **Never write secrets, keys, connection strings or personal data in the notepad.**
9. **Production is the human's call.** Only the lead deploys or runs production migrations, and only when the human asks.

## Rules for builders (not the lead)
- Run shell commands **one per call** (no `&&` chains) and **in the foreground** (no background jobs).
- Write the failing test first, then the code. Run the full test suite before your handoff and quote the result.
- Commit on your branch; do not push or open PRs unless the task says so. The lead reviews and integrates.
- Where the task asks for a seam (e.g. `// HOOK: wired by lead`), leave exactly that comment and nothing else.
