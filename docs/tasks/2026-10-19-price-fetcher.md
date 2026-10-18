# Task: polite price fetcher for Amazon + Flipkart custom listings

**Assigned to:** agy  **Lead / reviewer:** claude  **Second review:** codex (read-only)
**Branch:** `feat/price-fetcher` (from `main`, after `feat/custom-listings` is merged)  **Worktree:** `../deal-scour-wt-agy`

## Goal
Keep real prices fresh for the household's **custom listings on Amazon and Flipkart** (staples like butter, cheese, bread, eggs, protein,
plus whatever else they add) by fetching each product page **a few times a day**, politely. Each successful fetch becomes a
`price_observation` with `source = "fetcher"`, so deals and plans use it like any other price. Quick-commerce platforms are **not** fetched:
Blinkit blocks with 403, Zepto and Instamart answer with bot challenges, and we never work around bot checks (ADR-004).

Parsers already exist: `app/sources/pages.py` (`parse_amazon_product`, `parse_flipkart_product`, `PageBlockedError`, `PageParseError`).

## Files you may touch (nothing else)
- `backend/app/sources/fetcher.py` (new)
- `backend/app/domain/models.py`: add `SourceStatus`
- `backend/migrations/versions/0006_source_status.py` (new)
- `backend/app/api/v1/sources.py` (new)
- `backend/app/core/config.py`: add `fetchers_enabled` (`DEALSCOUR_FETCHERS == "1"`, default off) and `fetch_interval_hours` (`DEALSCOUR_FETCH_INTERVAL_HOURS`, default 6, min 2)
- `backend/tests/sources/test_fetcher.py`, `backend/tests/api/test_sources.py` (new), `backend/tests/test_migrations.py`

`httpx` is already a runtime dependency (the lead adds it in the branch's first commit). No other new deps.

## Runtime boundary
`fetcher.py` takes its HTTP client, clock and sleep function as **parameters** (`http_get: Callable[[str], tuple[int, str]]`,
`now: Callable[[], datetime]`, `sleep: Callable[[float], None]`), so tests never touch the network or wait. The production wiring
(httpx client with timeout 15 s, a normal desktop browser User-Agent, `Accept-Language: en-IN`) lives in one small function.
No retries inside a run. No proxies, no cookie or session reuse, no login, no CAPTCHA handling.

## Behaviour (`fetcher.refresh_due_listings(session, household_id, *, http_get, now, sleep, interval_hours) -> RefreshReport`)
1. **Due listings:** the household's non-archived custom listings with platform in {amazon, flipkart} whose latest `fetcher` observation is
   older than `interval_hours`, or that have none. Oldest first, **max 30 per run**.
2. **Per-platform gate:** skip a platform whose `source_status.disabled_until` is in the future.
3. **Politeness:** at least **10 s** between requests to the same platform (call `sleep`); requests are sequential.
4. **Fetch + parse:** status 200 → parser. Success → insert `PriceObservation(source="fetcher", listed_paise, mrp_paise = parsed MRP or,
   if None, max(listed, previous MRP for that listing, listed), in_stock)` and reset the platform's `consecutive_failures` to 0.
5. **Failures:** non-200, `PageBlockedError` or network error → `consecutive_failures += 1`, `last_error` (short, no page content).
   At **3** consecutive failures → `disabled_until = now + 24 h` and stop that platform for this run. A `PageParseError` counts as a failure
   for that listing only (doesn't disable the platform) and is recorded in the report.
6. **Report:** `RefreshReport(fetched: int, updated: list[listing_id], failed: list[(listing_id, reason)], skipped_platforms: list[str])`.

## Scheduling
- If `fetchers_enabled`, an app **lifespan** background thread runs `refresh_due_listings` for every household every `fetch_interval_hours`,
  with the first run 60 s after start. One loop per process. Exceptions are logged and never crash the app. Off by default.
- `POST /api/v1/sources/refresh` (owner only) → queues a run for the caller's household via `BackgroundTasks` → 202 `{"queued": n_due}`.
  409 if a run for that household is already in progress (in-process lock).
- `GET /api/v1/sources/status` → per platform: `{platform, enabled_by_config, consecutive_failures, disabled_until, last_success_at, last_error}`,
  plus `quick_commerce: "manual only (blocked by the sites)"`.

## Schema: `source_status`
`platform` PK, `consecutive_failures` int, `disabled_until` datetime|null, `last_success_at` datetime|null, `last_error` str|null ≤ 200.
Global, not per household: it describes how the site treats our requests.

## Test cases (write first, with fake `http_get`, fake `now`, recording `sleep`)
1. Two due Amazon listings and one Flipkart listing → 3 fetch calls. `sleep` was called so that same-platform gaps total ≥ 10 s. 3 observations
   with `source "fetcher"`, values from the real fixtures (`tests/fixtures/sources/*.html.gz`, decompressed): Amazon 180000, Flipkart 24000 (MRP 34900).
2. Not due: a listing with a fetcher observation 1 h old (interval 6) is not fetched. 7 h old is fetched.
3. MRP fallback: an Amazon page with no MRP → observation MRP = max(listed, previous MRP).
4. Blocked: the fake returns the Amazon captcha page 3 times in a row → the third failure sets `disabled_until = now + 24h`. The remaining Amazon
   listings are skipped (`skipped_platforms` includes amazon), and Flipkart is still fetched. Next run before 24 h → amazon skipped. After → tried again.
5. Success resets `consecutive_failures` to 0.
6. ParseError on one listing → recorded in `failed`, the platform is not disabled, and other listings continue.
7. Never fetches blinkit/zepto/instamart custom listings, nor seed listings.
8. Max 30 per run: 35 due → 30 fetched, oldest first.
9. Household isolation: refreshing household 1 never fetches household 2's listings.
10. API: `POST /sources/refresh` as owner → 202 with the due count. As member → 403. A concurrent second call → 409. `GET /sources/status` shape.
11. `fetchers_enabled` false → no background thread started (assert via a flag or app.state). True → the loop is registered (don't run it in tests).
12. Deals show the fetched price with `price_source "fetcher"` and `freshness "fresh"`.
13. Migration 0006 upgrades from 0005 with data intact.

## Done when
- [ ] All cases pass. The full suite passes 3× in a row. mypy and ruff are clean. Commit on `feat/price-fetcher` (no push). `handoff` + `release`.

## Don'ts
**No real network calls in tests.** No retries, proxies, CAPTCHA solving, rotating User-Agents, or headless browsers. Don't fetch quick-commerce
sites. Don't edit `app/main.py` except where noted by the lead (the lead wires the router and lifespan). No inline `python -c`.
