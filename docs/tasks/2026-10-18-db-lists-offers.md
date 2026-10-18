# Task: database foundation + persisted lists and offers

**Assigned to:** agy  **Lead / reviewer:** claude  **Second review:** codex (read-only)
**Branch:** `feat/db-lists-offers` (from `main`, after `feat/product-identity` is merged)  **Worktree:** `../deal-scour-wt-agy`

## Goal
Lists, needs and offers survive a restart. Add SQLite via SQLModel + Alembic (ADR-003) and CRUD APIs for **lists/needs** and the
**Offer Wallet**. There's no auth yet: everything belongs to one default household returned by a single seam function, so the auth
task only has to replace that function.

The lead has already added `sqlmodel` and `alembic` to `pyproject.toml` and installed them in the shared venv. **Do not pip install.**

## Files you may touch (nothing else)
- `backend/app/core/config.py` (new): `Settings` from env
- `backend/app/core/db.py` (new): engine, session dependency, SQLite pragmas
- `backend/app/domain/models.py` (new): SQLModel tables
- `backend/app/domain/need_rules.py` (new): shared need validation (moved out of plans.py)
- `backend/app/api/v1/plans.py`: only to import and use `need_rules` instead of its private copy (behaviour unchanged)
- `backend/app/api/v1/lists.py` (new), `backend/app/api/v1/offers.py` (new)
- `backend/alembic.ini` (new), `backend/migrations/env.py`, `backend/migrations/script.py.mako`, `backend/migrations/versions/0001_initial.py` (new)
- `backend/tests/conftest.py` (new), `backend/tests/api/test_lists.py`, `backend/tests/api/test_offers.py`,
  `backend/tests/domain/test_need_rules.py`, `backend/tests/test_migrations.py` (new)

## Runtime boundary
Server-side. `config.py` is the **only** place that reads environment variables:
`DEALSCOUR_DB_PATH` (default `./data/dealscour.db`, parent dir created on first use). Use a plain frozen dataclass with `from_env()`.
No pydantic-settings. Tests never touch `./data`: they use a temp-file SQLite per test through a dependency override in `conftest.py`.
Money columns are `int` paise. Timestamps are UTC `datetime` set by the server.

## Schema (`models.py`) — table names in snake_case
- `household`: `id` PK, `name` str, `pincode` str (6 digits). Migration 0001 **inserts household id=1**, "Home", "411018".
- `shopping_list`: `id` PK, `household_id` FK, `name` str 1..60, `kind` `"quick"|"monthly"|"event"`, `archived` bool=false, `created_at`.
- `need`: `id` PK, `list_id` FK (cascade delete), `line_id` str 1..80 (unique within its list), `product_key` str|null,
  `family_key` str|null, `quantity` str|null, `qty` int 1..99, `need_by_minutes` int|null, `lock_platform` str|null,
  `status` `"open"|"planned"|"bought"|"dropped"` = open, `created_at`, `updated_at`.
- `offer`: `id` PK, `household_id` FK, `code` str 1..20 (the id used in plans, e.g. "A1", unique per household among non-archived),
  `platform`, `kind`, `min_order_paise`, `value_paise`, `rate_bp`, `cap_paise` null, `tiers_json` str (JSON list of [min, value]),
  `uses_left`, `stack_group`, `value_type`, `multiplier_bp` null, `eligible_categories_json` str|null, `valid_to` date|null,
  `note` str|null ≤ 200, `archived` bool=false, `created_at`.

## `need_rules.py`
`validate_need(product_key, family_key, quantity, qty, catalog) -> None` raises `ValueError` with the same messages plans.py uses
today: exactly one key, quantity rules, known keys, unit match. Both plans.py and lists.py call it (plans maps ValueError → 422 as now).
Also `offer_from_record(...)` / `offer_to_optimizer(...)`. Whatever is cleanest, but building an optimizer `Offer` from a stored offer
must reuse the **same** validation path as the plans request (construct `app.optimizer.contract.Offer`, ValueError → 422).

## API (prefix `/api/v1`, routers `lists.router` and `offers.router`; the lead wires them in main.py)
`def current_household_id() -> int: return 1  # HOOK: replaced by auth (ADR-013)`. It lives in `core/db.py`, and every endpoint depends on it.
- `GET /lists` → non-archived lists of the household, newest first, each with `open_needs` count.
- `POST /lists` `{name, kind}` → 201 + list.
- `GET /lists/{id}` → list + needs (all statuses), sorted by created_at, id. 404 if not in household.
- `PATCH /lists/{id}` `{name?, archived?}`.
- `POST /lists/{id}/needs` `{line_id, product_key|family_key, quantity?, qty?, need_by_minutes?, lock_platform?}` → 201. Validated
  with `validate_need` → 422. Duplicate `line_id` in the list → 409.
- `PATCH /needs/{id}` (any of the editable fields + `status`) → re-validated. `DELETE /needs/{id}` sets `status = "dropped"` (no hard delete) → 200.
- `GET /offers?include_archived=false` · `POST /offers` (body = the plans `OfferIn` shape + `code`, `valid_to?`, `note?`) → 201.
  The offer must construct as an optimizer `Offer` → else 422. Duplicate active `code` → 409.
- `PATCH /offers/{id}` (uses_left, valid_to, note, archived) · `POST /offers/{id}/archive`.

## Test cases (write first)
1. Migrations: `alembic upgrade head` on an empty temp DB creates exactly the 4 tables and household 1. Then
   `SQLModel.metadata` and the migrated schema have the same table and column names (compare via `sqlalchemy.inspect`).
2. Pragmas: on a fresh connection `PRAGMA foreign_keys` = 1 and `PRAGMA journal_mode` = wal (file DB).
3. Lists: create → appears in GET /lists with `open_needs 0`. Add 2 needs (one exact `fortune_sunlite_oil_5l`, one flexible
   `sunflower_oil` + "5L") → `open_needs 2`. Archive → hidden from GET /lists.
4. Need validation: both keys → 422. Flexible without quantity → 422. Unknown product → 422. Duplicate line_id in a list → 409.
   The same line_id in another list → OK.
5. PATCH need status → planned/bought. DELETE → dropped (the row still exists in GET /lists/{id}). PATCH with an invalid combination → 422.
6. 404 for another household's list: insert a household 2 + list directly in the DB → GET /lists/{id} → 404.
7. Offers: POST valid flat offer → 201. GET shows it. POST same code again → 409. POST `kind: flat, value_paise: 0` → 422.
   Tiered with malformed tiers → 422. Archive → hidden by default, shown with `include_archived=true`. After archiving, the code can be reused.
8. Round-trip: a stored tiered offer with `eligible_categories ["dryfruits"]` converts back into an optimizer `Offer` equal to one
   built directly.
9. Persistence across app instances: create a list with app A on a temp DB file, then build a new app/engine on the same file → the list is there.
10. Existing plans tests still pass unchanged (need validation moved, not altered).

## Done when
- [ ] All cases pass. The full suite passes 3× in a row. mypy and ruff are clean. Commit on `feat/db-lists-offers` (no push).
- [ ] `handoff` to claude, then `release`.

## Don'ts
No new dependencies, no pip. Don't edit `app/main.py`, pricing, the optimizer or seed data. No hard deletes. No inline `python -c`.
One command per call, foreground only.
