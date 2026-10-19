# Task: deal radar — read Telegram deal channels, alert only on real deals

**Assigned to:** agy (model: gemini-4-argon-high)  **Lead / reviewer:** claude  **Second review:** codex (read-only)
**Branch:** `feat/deal-radar` (from `main`; #31, #33 and #34 are merged)  **Worktree:** `../deal-scour-wt-agy`
**Depends on:** the extension (PR #31) and the staples tracker (price history, watches, `/deals/feed`).

## Goal
The owner follows Telegram deal channels (e.g. "Offer Box 2.0", 196k subscribers; posts look like `Loot ₹99 : https://amzn.to/…`, ~95% not groceries).
While Telegram Web is open in Chrome, the extension passes new posts from channels the owner chose to DealScour. The server works out which
product each link is, decides whether it is **really a good deal for this household**, and only then alerts them by a browser notification and
a Telegram message from their own bot.

## Decisions already made (owner, 2026-10-19)
- Read via the **extension** from the user's open Telegram Web tab. No Telegram login, API id or session is stored anywhere.
- Alerts: **browser notification** (extension) + **Telegram bot** to the owner (BYOK: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`). No WhatsApp.

## Files you may touch (nothing else)
- `extension/telegram-reader.js` (new content script), `extension/manifest.json` (add `https://web.telegram.org/*` to content script matches and
  host permissions, `notifications` and `alarms` permissions), `extension/options.html`, `extension/options.js` (new), `extension/service-worker.js`,
  `extension/lib.js`, `extension/tests/*.test.js`
- `backend/app/radar/{__init__,posts,links,verdict}.py` (new), `backend/app/notify/{__init__,base,telegram}.py` (new)
- `backend/app/api/v1/radar.py` (new), `backend/app/core/extension_auth.py` (new), `backend/app/domain/models.py` (`RadarChannel`, `RadarPost`, `RadarAlert`, `RadarKeyword`),
  `backend/migrations/versions/0009_radar.py` (new), `backend/app/core/config.py` (Telegram bot settings, quiet hours, daily alert cap)
- `.env.example`, `backend/tests/radar/*`, `backend/tests/api/test_radar.py`, `backend/tests/test_migrations.py`
- `web/src/features/radar/RadarPage.tsx` (new: channels, keywords, recent verdicts, Connect extension), `extension/portal-bridge.js`, `web/src/features/deals/DealsPage.tsx` (Telegram section),
  `web/src/App.tsx`, `web/src/lib/api.ts`, matching tests

## Runtime boundary
- **Extension:** reads the DOM of `web.telegram.org` only when the open chat's id (URL hash, e.g. `#-1001191090845`) is in the owner's channel list
  (set in DealScour, synced to the extension). It sends only `{peer_id, message_id, text, links[], posted_at}` for **new** channel posts. It never reads
  other chats, never sends names, phone numbers or private messages, and never clicks, types or sends anything in Telegram.
- **Server:** link resolution, verdicts, Telegram Bot API calls (`httpx`, no new deps). Bot token never logged or returned. Gemini optional, capped (as in the staples tracker).

## A. Ingest (`POST /api/v1/radar/posts`, batch ≤ 50)
1. Reject posts whose `peer_id` is not an enabled `RadarChannel` of the household. Dedupe on (household, peer_id, message_id). Keep text ≤ 2,000 chars.
2. Parse the post: prices (`₹`, `@`, `at`, a bare number before ` : http`), and links. One post can hold several (price, link) pairs
   (`854 : link1 / 859 : link2`); pair each link with the nearest price before it.

## B. Link resolution (`radar/links.py`)
3. Direct product links (`amazon.in/dp/…`, `flipkart.com/…/p/…?pid=`) → `parse_product_url` (drop affiliate `tag` and tracking).
4. Short links from an allow-list only: `amzn.to`, `link.amazon`, `amzn.in`, `fkrt.it`, `fkrt.cc`, `dl.flipkart.com/s/`. Follow redirects manually (≤ 4 hops, https,
   every hop host must be on the allow-list or an Amazon/Flipkart host), no body download beyond 256 KB. Anything else (myntr.it, clnk.in, bit.ly) → `unsupported`.
5. Politeness: ≤ 1 resolution per 2 s, ≤ 120 per hour; cache resolved short links for 7 days.

## C. Verdict (`radar/verdict.py`, pure function + tests)
6. **Tracked product** (a household listing with the same platform+sku): GOOD if posted price ≤ target, or ≤ 30-day low with ≥ 3 observations, or
   ≥ 15% under the 30-day average.
7. **Untracked product:** fetch its page once through the existing fetcher (Amazon/Flipkart only, same lock and limits) for title, price and pack.
   It is a candidate only if its title matches a household keyword (`RadarKeyword`, e.g. "whey", "peanut butter", "almonds") or a family the household
   tracks. GOOD if its unit price is ≥ 10% below the best current unit price in that family (fresh/ok prices only).
8. **Verify before alerting:** the live page price (from 7, or a fetch for tracked items) must be ≤ posted price + 5% and in stock. Otherwise verdict
   `expired`. Save the live price as a `fetcher` observation (feeds history).
9. Store every verdict with reasons (`below_target`, `30d_low`, `under_avg`, `beats_family_best`, `expired`, `not_relevant`, `unsupported_link`).

## D. Alerts (`notify/`)
10. `Notifier` protocol; `TelegramNotifier` (Bot API `sendMessage`, plain text: product, price, why, link without affiliate tag); browser alerts are
    served by `GET /radar/alerts?since=` which the extension polls every 2 min (`chrome.alarms`) and shows with `chrome.notifications`
    (click → product page).
11. Dedupe: one alert per (product, price) per 24 h. Quiet hours 23:00–07:00 (configurable) hold Telegram messages until 07:00. Max 10 alerts/day.
    Telegram is skipped silently when the token or chat id is empty.

## E. Web
12. **Radar** page: add a channel (paste the Telegram Web URL or id + a name), turn it on/off, keywords chips, last 50 posts with verdict and reason,
    a "Send test alert" button. **Deals** tab: a "From Telegram" section with GOOD verdicts.

## Test cases (write first; fake http, fake clock, fake Telegram)
1. Parse "Loot ₹99 : https://amzn.to/x", "854 : l1\n859 : l2", "Pampers 42 pcs @828 https://link.amazon/y", "₹1,224*" → right (price, link) pairs.
2. Resolve amzn.to → amazon.in/dp/ASIN?tag=… → canonical without tag. A hop to a non-allowed host → `unsupported`. myntr.it → `unsupported`.
3. Tracked butter at ₹290 with target ₹300 → GOOD `below_target`. ₹330 with 30-day low ₹300 → `not_relevant`.
4. Untracked whey (keyword "whey") 1kg at ₹2,400 when family best is ₹2,899/kg → GOOD `beats_family_best`. Luggage → `not_relevant`, no page fetch.
5. Live price ₹2,999 vs posted ₹2,400 → `expired`, no alert. Out of stock → `expired`.
6. Dedupe, quiet hours (held then sent at 07:00), daily cap 10, Telegram skipped without token; token never in responses or caplog.
7. Posts from a channel not on the list → 422/ignored. Another household's channel → ignored.
8. Extension: `extractChannelPosts(dom-like objects, allowedPeers)` returns only new posts for allowed peers; ignores other chats; strips nothing but
   text/links/ids. Notification click opens the product url only if `isAllowedUrl`.
9. Migration 0009 upgrades from 0008 with data intact.

## Done when
- [ ] All cases pass; full suites 3× green; mypy, ruff, eslint, tsc, extension tests clean. Commit on `feat/deal-radar` (no push). `handoff` + `release`.

## Don'ts
No Telegram login/MTProto/userbot, no reading chats outside the list, no clicking or sending in Telegram, no WhatsApp, no new deps, no Telegram or
Gemini calls in tests. Don't edit `app/main.py` (lead wires router + startup). No inline `python -c`. One command per call, foreground only.

## Added by the lead (2026-10-19, before you start)
13. **Extension → server auth (new).** Until now only the DealScour page called the API. The radar's extension calls it from the
    service worker while Telegram Web is the open tab, so it needs its own credential:
    - `POST /radar/extension-token` (normal session auth + CSRF header) creates a random 32-byte token and returns it **once**. Only its
      SHA-256 is stored (`RadarExtensionToken(household_id, token_hash, created_at, last_used_at, revoked)`, in migration 0009).
      Creating a new token revokes the old one.
    - The Radar page has a **Connect extension** button. It sends the token through `portal-bridge.js` (`DEALSCOUR_SET_RADAR_TOKEN`, from
      `PORTAL_ORIGINS` only), and the worker saves it in `chrome.storage.local`. The page shows "Extension connected" (the worker answers ok).
    - `POST /radar/posts` and `GET /radar/alerts` accept **only** `Authorization: Bearer <token>`: no session cookie, no CSRF header. A
      constant-time hash compare; revoked or unknown → 401. No other endpoint accepts this token.
    - The worker calls `http://localhost:8000` (configurable as `DEALSCOUR_API_ORIGIN` in `lib.js`, which must be one of `PORTAL_ORIGINS`).
      Add that origin to `host_permissions`.
14. **Content-script scope.** `telegram-reader.js` gets its own `content_scripts` entry for `https://web.telegram.org/*` only. It doesn't load
    `portal-bridge.js`, and the portal entry stays on `PORTAL_ORIGINS`. The worker accepts `DEALSCOUR_RADAR_POSTS` only from a sender whose
    tab URL host is exactly `web.telegram.org` and whose `sender.id` is ours.
15. **Allowed peers come from the server:** `GET /radar/channels` (bearer) → enabled peer ids. Cache them in `chrome.storage.local` and refresh
    with the 2-minute alarm. The reader sends nothing until the list is loaded.
16. **Notification links:** a `chrome.notifications` click opens the alert's product URL only if `isProductPageUrl` (lib.js) accepts it.
17. Startup job for held quiet-hour messages: expose `send_due_alerts(session, now, notifier)` in `notify/`. **Don't** add a scheduler; the lead
    wires it in `app/main.py`'s lifespan (`// HOOK` comment in your handoff).

Extra test cases:
10. Token: create → bearer works on posts/alerts; second create → the first is 401; the token never appears in GET responses or caplog; a session
    cookie alone on `/radar/posts` → 401.
11. Worker: `DEALSCOUR_RADAR_POSTS` from a non-telegram tab → ignored; `DEALSCOUR_SET_RADAR_TOKEN` from a non-portal origin → ignored.
12. Reader with no peer list loaded → sends nothing.
18. **Extension version you can see (owner request).**
    - Set `extension/manifest.json` `"version"` to `"0.3.0"` (0.1.0 = #31, 0.2.0 = #34 retroactively, 0.3.0 = radar).
    - `portal-bridge.js` reports `chrome.runtime.getManifest().version`; no hard-coded `'0.1.0'` anywhere.
    - The options page shows "DealScour extension v<version>".
    - Web: `web/src/lib/extension.ts` exports `EXPECTED_EXTENSION_VERSION`, read at build time from `extension/manifest.json`
      (JSON import; allow it in the Vite/TS config if needed: `web/vite.config.ts`, `web/tsconfig*.json` are allowed for this only).
    - The header gets a small badge (`web/src/App.tsx`): "Extension 0.3.0 ✓" (green) when it matches; "Reload the extension: 0.2.0 loaded,
      0.3.0 available" (amber, with the text "chrome://extensions") when it's older; "Extension not found" (grey) when there's no answer to the
      ping within 1 s.
    - Tests: the bridge test checks the version comes from the manifest; the web test renders the 3 badge states.
