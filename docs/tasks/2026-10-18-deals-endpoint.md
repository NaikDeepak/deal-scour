# Task: `GET /api/v1/deals` (membership-aware deal grid from the seed catalog)

**Assigned to:** agy  **Lead / reviewer:** claude  **Second review:** codex (read-only)
**Branch:** `feat/deals-endpoint` (from `main`, after `feat/pricing-core` is merged)  **Worktree:** `../deal-scour-wt-agy`

## Goal
Return the deal grid the prototype's Deals tab showed, computed correctly. Item prices depend on memberships,
delivery is shown as an **order-level condition** (not added to the item), unit rates make pack sizes comparable,
and the "best" badge is chosen **per product by unit rate**. This is the Phase 0 exit criterion in `docs/ROADMAP.md`.
It fixes prototype defects D4, D5, D7 and D15 (`docs/CODE_ANALYSIS.md` §4).

## Files you may touch (nothing else)
- `backend/app/domain/catalog.py` (new)
- `backend/app/api/v1/deals.py` (new)
- `backend/tests/domain/__init__.py` (new, empty), `backend/tests/domain/test_catalog.py` (new)
- `backend/tests/api/__init__.py` (new, empty), `backend/tests/api/test_deals.py` (new)

Use, but do not modify: `app/core/money.py`, `app/pricing/*`, `app/seed/prototype_catalog.json`.

## Runtime boundary
Server-side Python only. `catalog.py` may read the packaged JSON (`importlib.resources.files("app.seed")`). Nothing
else does I/O. No database yet: the catalog is loaded in memory. No new dependencies. All money stays `int` paise.
`mypy` (the strict sections) and `ruff check` must be clean.

## API to implement

### `app/domain/catalog.py`
```python
@dataclass(frozen=True)
class SeedListing:
    id: str; product_key: str; category: str; title: str; brand: str; pack_label: str
    platform: Platform            # from app.pricing.fee_schedules
    listed: Paise; mrp: Paise; member_discount: Paise
    eta_minutes: int; is_instant: bool; coupon_text: str | None; url: str; icon: str; source: str
    @property
    def pack(self) -> Pack: ...                       # parse_pack(pack_label)
    def item_price(self) -> ItemPrice: ...            # ItemPrice(listed, mrp, member_price=listed - member_discount)

def load_seed() -> list[SeedListing]                  # from app/seed/prototype_catalog.json, keys *_paise → fields
def rate_basis(category: str, unit: Unit) -> tuple[int, str]
    # "dryfruits" with unit "g" -> (100, "100g"); everything else -> default_basis(unit)
```

### `app/api/v1/deals.py`
`router = APIRouter()` with `GET /deals`. **Do not edit `app/main.py`.** The lead wires the router. Tests mount it on
their own `FastAPI()` app with prefix `/api/v1`.

Query params:
- `members`: comma-separated platforms whose membership is ON. Default `"amazon,instamart,flipkart"` (the prototype default).
  An empty string means none. An unknown platform gives **422**.
- `category`, `platform`: exact match filters, optional. An unknown platform gives 422.
- `q`: optional, case-insensitive substring match on title, brand or category.
- `sort`: `unit_rate` (default) | `price` | `discount` | `eta`. Ascending, except `discount`, which is descending. Ties break by `id`. Unknown values give 422.

Response: `{"count": int, "deals": [DealOut, ...]}` with Pydantic v2 `DealOut`:
```
id, product_key, category, title, brand, platform, pack_label, icon, url, coupon_text, source,
is_member: bool,
listed_paise, mrp_paise, unit_price_paise,          # unit_price from pricing.landed.unit_price (no fees)
discount_bp,                                        # pricing.landed.discount_bp
unit_rate_paise, rate_basis_label,                  # e.g. 5540, "kg"
delivery_fee_paise,                                 # SAMPLE_SCHEDULES[platform].delivery_fee, or 0 when the effective threshold is 0
free_delivery_min_paise: int | None,                # effective threshold for this membership state (member_free_delivery_min if member and not None, else free_delivery_min)
eta_minutes, is_instant,
is_best_in_product: bool                            # lowest unit_rate_paise among ALL listings with the same product_key
                                                    # (computed before filters; ties → all tied listings true)
```

## Test cases (write these first, make them fail, then implement)

**catalog**
1. `load_seed()` returns 28 listings, ids unique, every `pack_label` parses, every platform is one of the 5.
2. `wal-1` has `product_key == "nutraj_walnuts"` (not almonds).
3. `SeedListing` for `stp-1`: `item_price() == ItemPrice(listed=29200, mrp=36500, member_price=27700)`.
4. `rate_basis("dryfruits", "g") == (100, "100g")`, `rate_basis("staples", "g") == (1000, "kg")`, `rate_basis("cleaning", "ml") == (1000, "L")`.

**deals (default members = amazon, instamart, flipkart)**
5. `GET /api/v1/deals` → 200, `count == 28`, and the `deals` list is sorted by `unit_rate_paise` ascending, ties by id.
6. `stp-1` (Instamart, member): `unit_price_paise == 27700`, `unit_rate_paise == 5540`, `rate_basis_label == "kg"`, `discount_bp == 2410`, `delivery_fee_paise == 2500`, `free_delivery_min_paise == 19900`, `is_member is True`.
7. `stp-3` (Blinkit, not member): `unit_price_paise == 28900`, `unit_rate_paise == 5780`, `delivery_fee_paise == 2500`, `free_delivery_min_paise == 19900`, `is_member is False`.
8. `stp-2` (Amazon, Prime): `unit_price_paise == 28300`, `delivery_fee_paise == 0`, `free_delivery_min_paise == 0`.
9. Best per product: among `aashirvaad_atta`, only `stp-1` has `is_best_in_product`. Among `california_almonds`, `alm-1` is best with `unit_rate_paise == 6190` and label `"100g"`. `alm-2` → 8000, `alm-3` → 8300. `wal-1` is best of its own product.
10. **Regression D4/D15:** no field adds delivery to the item. For every deal, `unit_price_paise` equals `pricing.landed.unit_price(...)` for that membership state.

**deals (other params)**
11. `members=blinkit` → `stp-3` `unit_price_paise == 27700`, `free_delivery_min_paise == 0`, and is now the only atta with `is_best_in_product`. `stp-1` → 29200, `free_delivery_min_paise == 49900`.
12. `members=` (empty) → every `is_member` is false. Amazon `stp-2` → `delivery_fee_paise == 4000`, `free_delivery_min_paise == 49900`.
13. `members=amazon,bigbasket` → 422. `platform=bigbasket` → 422. `sort=cheapest` → 422.
14. `category=dryfruits` → only dry fruits, and `is_best_in_product` is unchanged from the unfiltered result.
15. `q=AASHIRVAAD` → exactly the 3 atta listings. `q=zzz` → `count == 0`, `deals == []`.
16. `platform=amazon&sort=price` → only Amazon, `unit_price_paise` ascending.
17. `sort=discount` → `discount_bp` descending. `sort=eta` → `eta_minutes` ascending.

## Seams
Leave this comment as the last line of `app/api/v1/deals.py`:
`# HOOK: app.include_router(deals.router, prefix="/api/v1") in app/main.py (wired by lead)`

## Done when
- [ ] All cases pass. The full suite (`.venv/bin/python -m pytest` from `backend/`) passes 3 runs in a row.
- [ ] `.venv/bin/python -m mypy` and `.venv/bin/python -m ruff check .` are clean.
- [ ] Commit on `feat/deals-endpoint` (no push).
- [ ] `scripts/collab.sh handoff agy claude "feat/deals-endpoint · <done> · <test result> · <anything unsure>"`
- [ ] `scripts/collab.sh release agy`

## Don'ts
- No new dependencies. No edits outside the file list (especially `app/main.py` and `app/pricing/*`).
- No database, no caching layer, no background work. One command per call, foreground only.
