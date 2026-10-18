# Architecture Decision Records

Format: **Context → Decision → Consequences**. Status is one of `Accepted`, `Proposed`, `Superseded by ADR-x`.
Add new ADRs at the bottom and never rewrite an accepted one. Supersede it instead.

| # | Title | Status |
|---|---|---|
| 001 | Personal / friends-and-family scale, self-hosted | Accepted |
| 002 | Python FastAPI backend + React TS PWA | Accepted |
| 003 | SQLite (WAL) as the database | Accepted |
| 004 | Price data via provenance-tagged adapters; scraping opt-in only | Accepted |
| 005 | Offers are user-entered structured rules (Offer Wallet) | Accepted |
| 006 | Optimizer: pure function, OR-Tools CP-SAT with heuristic fallback | Accepted |
| 007 | Return 2–3 labelled plans, not a single answer | Accepted |
| 008 | Pending basket is a first-class entity | Accepted |
| 009 | Money as integer paise | Accepted |
| 010 | Cashback valuation multipliers and confidence ρ | Accepted |
| 011 | Fees are order-level | Accepted |
| 012 | Need → Product → Listing identity hierarchy | Accepted |
| 013 | Invite-only email OTP auth; households and circles | Accepted |
| 014 | In-process APScheduler instead of system cron | Accepted |
| 015 | Alerts via Web Push + Telegram; WhatsApp deferred | Accepted |
| 016 | Rule-based list parsing; optional LLM fallback | Proposed |
| 017 | Docker Compose deployment with Caddy | Accepted |
| 018 | Freeze prototype as reference | Accepted |
| 019 | Single source of truth for pricing/optimization (server) | Accepted |
| 020 | Never auto-checkout or store platform credentials | Accepted |
| 021 | AGENTS.md is canonical; CLAUDE.md imports it | Accepted |
| 022 | Open source, BYOK: each deployment brings its own keys | Accepted |
| 023 | Ship the heuristic first; defer CP-SAT until it's needed | Accepted (amends 006) |

---

### ADR-001 · Personal / friends-and-family scale, self-hosted
*2026-10-18 · Accepted*
**Context.** The app is for one planner plus about 15 family and friends. No commercial intent.
**Decision.** Optimise for low cost, low ops and trust. Single instance, invite-only, no ads or affiliate ranking.
**Consequences.** Simple infrastructure. We can use opinionated defaults (pincode 411018, INR, IST). No need for multi-tenant isolation beyond household scoping.
Features like SEO, public catalogs and A/B testing are out of scope.

### ADR-002 · Python FastAPI backend + React TS PWA
*Accepted*
**Context.** The prototype is Python plus a single HTML file. The optimizer needs a good MIP/CP solver. Family members use phones.
**Options.** (a) All-TypeScript (Next.js + glpk.js). (b) Python API + React PWA. (c) Keep single HTML + localStorage.
**Decision.** (b). OR-Tools CP-SAT is first-class in Python, as are scraping tools (httpx/Playwright) and data work. An installable PWA
gives a phone app feel without app stores and supports Web Push.
**Consequences.** Two languages. The TS client is generated from OpenAPI to avoid drift. Business logic stays in Python (ADR-019).

### ADR-003 · SQLite (WAL) as the database
*Accepted*
**Context.** Fewer than 20 users and a few thousand price observations a month. One process.
**Decision.** SQLite in WAL mode via SQLModel/SQLAlchemy, Alembic migrations, nightly `.backup`.
**Consequences.** Zero ops. Stick to portable SQL so Postgres is a config change if we ever run multiple writers. Use JSON columns sparingly
(offer params, memberships), and validate them with Pydantic.

### ADR-004 · Price data via provenance-tagged adapters; scraping opt-in only
*Accepted*
**Context.** None of the five platforms offers a public grocery price API. Quick-commerce prices depend on pincode and dark store, and their
apps and sites restrict automated access in their terms. The prototype's "live scour" is an animation over hard-coded data.
**Decision.** Use a `SourceAdapter` interface. Every `PriceObservation` records `source`, `observed_at`, `pincode` and observer. Build order:
manual entry → link paste → browser-extension capture (prices on pages the user is already viewing) → optional Amazon PA-API →
optional per-platform fetchers. Fetchers are personal-use only, limited to watched items, rate-limited, never log in or bypass CAPTCHAs,
default off, and auto-disable after repeated failures.
**Consequences.** Early on, prices are crowd-sourced within the family, which is fine at this scale and fully legitimate. Freshness is
always visible. The optimizer down-weights stale prices and flags them (`STALE_PRICE`). The app works even with every fetcher off.

### ADR-005 · Offers are user-entered structured rules (Offer Wallet)
*Accepted*
**Context.** Threshold offers ("₹50 on ₹500") are often personalised, shown inside the apps, or arrive by SMS. Scraping them is unreliable.
**Decision.** Offers are entered from templates into a typed schema (`BASKET_OPTIMIZER.md` §3) and tied to a **platform account**,
with `uses_left`, validity, stack group and value type. Offers can be shared to a household or circle as a *prompt*, not as a usable instance.
**Consequences.** It takes about 20 s to add an offer, but the data is exactly right. It also enables "Do you have this offer too?" in circles.

### ADR-006 · Optimizer: pure function, OR-Tools CP-SAT with heuristic fallback
*Accepted*
**Context.** Order packing with threshold offers is a bin-covering / multiple-knapsack variant with fees and stacking rules. Instances are
small (≤ 40 lines, ≤ 5 platforms, ≤ 6 orders per platform).
**Decision.** Model it exactly in CP-SAT with integer paise, a 1 s budget and 8 workers. A deterministic greedy + local-search heuristic acts as the fallback
and preview. The optimizer is a pure function `plan(PlanRequest) -> PlanSet` with no I/O, and `today` is an input.
**Consequences.** Optimal or near-optimal plans in under 1.5 s. Easy golden tests and replay of stored requests. The heuristic must be kept
consistent with CP-SAT through cross-check tests.

### ADR-007 · Return 2–3 labelled plans, not a single answer
*Accepted*
**Context.** "Cheapest" depends on how much you value waiting, effort and the risk of an unfinished pending basket.
**Decision.** Always return *Cheapest now*, *Max savings* (pending allowed) and *Fastest*, deduplicated, each with savings vs baseline and reasons.
**Consequences.** The user stays in control. The UI must make the difference between plans obvious in one line.

### ADR-008 · Pending basket is a first-class entity
*Accepted*
**Context.** Splitting orders only pays off if leftover orders can wait and be topped up later.
**Decision.** `basket` has a status machine (`FLOW.md` §4) with shortfall, deadline, target offers and filler suggestions. Pending baskets
take part in planning, alerts and pooling.
**Consequences.** It needs a `check_pending` job and nudges. Adding any need can prompt "add to pending basket".

### ADR-009 · Money as integer paise
*Accepted*
**Context.** The prototype mixes `round(x, 1)` in Python with `Math.round` in JS, which gives different totals. A float rounding can flip ₹499.995 across a ₹500 threshold.
**Decision.** Store and compute all money as `int` paise. Format only at the edge (`formatINR`). Thresholds are compared in paise.
**Consequences.** CP-SAT coefficients are integral for free. Percent rates are basis points.

### ADR-010 · Cashback valuation multipliers and confidence ρ
*Accepted*
**Context.** ₹50 Amazon Pay balance ≠ ₹50 cash for everyone. SuperCoins are worth less. Some cashbacks never arrive.
**Decision.** Each offer value type has a multiplier (default: cash 1.0, Amazon Pay 1.0, SuperCoins 0.8). Pending-basket offer value is counted
at confidence ρ (default 0.8). ρ adapts downward per offer source when the ledger records missed cashbacks.
**Consequences.** Plans reflect real value. Settings expose these values with plain explanations.

### ADR-011 · Fees are order-level
*Accepted*
**Context.** The prototype adds the delivery fee to every item's "net landed price". A basket of 5 non-member items is then charged 5 fees,
which inflates the price of quick-commerce platforms.
**Decision.** Item landed price = listed − member price − item coupons. Delivery, handling, platform, small-cart and surge fees attach to an order
via a versioned, user-editable `fee_schedule` (with membership-specific free-delivery minimums).
**Consequences.** The deal grid shows "₹289 + delivery (free above ₹199)" instead of baking a fee into the item. The optimizer captures "add items here to cross free delivery".

### ADR-012 · Need → Product → Listing identity hierarchy
*Accepted*
**Context.** The prototype's `itemGroup` mixes products (walnuts sit in the `california_almonds` group). Keyword matching produces false hits.
**Decision.** A **Need** (what you want, possibly brand- or pack-flexible) resolves to one or more **Products** (canonical brand + pack), which have
**Listings** per platform and pincode. Comparisons across pack sizes use unit rate. Matching is fuzzy with a confidence threshold, and a
low-confidence match asks the user. It never defaults.
**Consequences.** We need a small catalog curation UI (merge duplicates, add aliases). The catalog grows from what the family actually buys.

### ADR-013 · Invite-only email OTP auth; households and circles
*Accepted*
**Context.** Family members vary in tech comfort. Telegram isn't universal and WhatsApp login is not free.
**Decision.** Email OTP (6 digits, 10-minute expiry) via a free transactional email tier, with invite links issued by household owners. Long-lived sessions. Roles:
owner, member, viewer. Circles link households for shared feeds and pooling.
**Consequences.** One SMTP dependency. Passkeys can be added later.

### ADR-014 · In-process APScheduler instead of system cron
*Accepted*
**Context.** The prototype suggests `*/30 * * * * python3 deal_scour_backend.py`, but the script has no persistence, so each run starts from hard-coded state.
**Decision.** APScheduler runs inside the app process with DB-backed job locks (`job_run`). Jobs are idempotent.
**Consequences.** One deployable unit. A single instance is required, which matches ADR-001.

### ADR-015 · Alerts via Web Push + Telegram; WhatsApp deferred
*Accepted*
**Context.** The prototype lists Telegram, WhatsApp and browser push. The WhatsApp Business API has per-conversation cost and an approval process.
**Decision.** Web Push (via the PWA, using VAPID) and a Telegram bot, which also accepts `/add`, `/list`, `/pending`. Both have dedupe keys, cooldown and quiet hours.
WhatsApp is revisited only with an ADR on cost.
**Consequences.** iOS users must "Add to Home Screen" for Web Push. Telegram is the fallback.

### ADR-016 · Rule-based list parsing; optional LLM fallback
*Proposed*
**Context.** Free-text lists ("2 surf matic 2l, amul ghee 1 ltr, atta") are mostly regular, with a long tail of messy lines.
**Decision.** A deterministic parser (qty, unit, pack, brand dictionary, synonyms such as *ltr → L* and *aata → atta*) handles the regular cases. An optional LLM
fallback (`claude-haiku-5-5`) handles only lines below a confidence threshold, returns structured JSON validated by Pydantic, and has a monthly spend cap. It is off by default.
**Consequences.** It works offline and for free by default. LLM output is a *suggestion* the user confirms.

### ADR-017 · Docker Compose deployment with Caddy
*Accepted*
**Decision.** `app` + `caddy` (automatic TLS). Run on a cheap VPS or a home box via Tailscale or Cloudflare Tunnel. Nightly SQLite backup with optional rclone to Drive.
**Consequences.** `docker compose up` is the whole deploy.

### ADR-018 · Freeze prototype as reference
*Accepted*
**Context.** `dealscour_v3.html` is 1 MB (87% is an inline base64 image) and uses the Tailwind CDN play script. Its logic is mocked.
**Decision.** In Phase 0, move both files to `prototype/`, unchanged and read-only. Port the *ideas*: membership-aware landed price, unit-rate comparison,
compare modal, matrix view, membership toggles. Do not port the code.
**Consequences.** There is one place to see the original UX intent. Bugs listed in `CODE_ANALYSIS.md` must not reappear.

### ADR-019 · Single source of truth for pricing/optimization (server)
*Accepted*
**Context.** The prototype implements landed-price logic twice (Python and JS) with different data and rounding.
**Decision.** Pricing and optimization exist only in `backend/app/pricing` and `backend/app/optimizer`. The web app shows API results.
**Consequences.** Re-planning needs a round-trip, which is fine because it takes under 1.5 s. The offline PWA can capture list items but not plan.

### ADR-020 · Never auto-checkout or store platform credentials
*Accepted*
**Context.** Automating checkout would require credentials, session cookies and payment access, with security, ToS and liability risks.
**Decision.** The app plans, deep-links to the platform, and provides a checkout checklist. Humans place orders.
**Consequences.** Some manual effort at checkout. There is no credential storage to protect.

### ADR-021 · AGENTS.md is canonical; CLAUDE.md imports it
*Accepted*
**Context.** Several AI coding tools are in use (Claude Code, Codex, Qodo). Duplicated instruction files drift.
**Decision.** `AGENTS.md` holds all project rules. `CLAUDE.md` contains `@AGENTS.md` plus Claude-only notes.
**Consequences.** Edit rules in one place.

### ADR-022 · Open source, BYOK: each deployment brings its own keys
*2026-10-18 · Accepted*
**Context.** The repo is public. Friends and family may run their own copy rather than share one instance. Some features
need third-party credentials (SMTP, Telegram bot, Web Push VAPID keys, an LLM API key, Amazon PA-API).
**Decision.** Bring-your-own-key. The repo ships no keys and no hosted service. Every credential comes from the deployer's
`.env` (template: `.env.example`). Each key-dependent feature is **off when its key is empty** and the app still works
(manual prices, no LLM parsing, in-app notifications only). Keys are never stored in the DB, logged, sent to the browser,
or written to the agent notepad. LLM usage stays capped per ADR-016.
**Consequences.** There's no shared cost, and each user's data and keys stay on their own box. Setup docs must list every key and what it unlocks.
CI and tests never need real keys.

### ADR-023 · Ship the heuristic first; defer CP-SAT until it's needed
*2026-10-18 · Accepted · amends ADR-006*
**Context.** ADR-006 planned CP-SAT as the primary solver with a heuristic fallback. The heuristic (`optimizer/heuristic.py`) was
measured against exhaustive search: **exact optimum on 150/150 random instances** (≤ 5 lines, up to 2 platforms, mixed flat and
%-cap offers), never worse than the baseline, and 0.16 s at 40 lines × 5 platforms. OR-Tools is a large dependency (slow installs
on the dev machine, an extra wheel for every self-hoster).
**Decision.** The heuristic is the production solver for v1. CP-SAT is deferred. Revisit when any of these happens: a golden or replayed
real plan where the heuristic is provably beaten; offer kinds 8–14 (multi-buy, Subscribe & Save) make local search weak;
or instances grow past ~60 lines.
**Consequences.** No OR-Tools dependency for now. `evaluate_plan` remains the single scorer, so a future CP-SAT model can be
cross-checked against it and the heuristic. The brute-force cross-checks stay in the test suite as a regression net.
