from collections.abc import Generator
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlmodel import Session

from app.api.v1.baskets import router as baskets_router
from app.api.v1.lists import router as lists_router
from app.api.v1.offers import router as offers_router
from app.api.v1.plans import router as plans_router
from app.core import clock
from app.core.db import get_session
from app.domain.catalog import load_seed
from app.pricing.landed import unit_price


@pytest.fixture
def baskets_client(engine: Engine) -> Generator[TestClient, None, None]:
    app = FastAPI()
    app.include_router(lists_router, prefix="/api/v1")
    app.include_router(offers_router, prefix="/api/v1")
    app.include_router(baskets_router, prefix="/api/v1")
    app.include_router(plans_router, prefix="/api/v1")

    def override_get_session() -> Generator[Session, None, None]:
        with Session(engine) as s:
            yield s

    app.dependency_overrides[get_session] = override_get_session
    with TestClient(app) as c:
        yield c


def _get_amazon_filler() -> Any:
    seed = load_seed()
    surf_amazon = next(
        item
        for item in seed
        if item.product_key == "surf_excel_matic_fl_liquid_2l" and item.platform == "amazon"
    )
    surf_price = unit_price(surf_amazon.item_price(), is_member=True)
    shortfall = 50000 - surf_price
    filler_listing = next(
        item
        for item in seed
        if item.platform == "amazon"
        and item.product_key not in {"surf_excel_matic_fl_liquid_2l", "fortune_sunlite_oil_5l"}
        and unit_price(item.item_price(), is_member=True) >= shortfall
        and unit_price(item.item_price(), is_member=True) <= 25000
    )
    return filler_listing


def test_1_ex_1_end_to_end(baskets_client: TestClient) -> None:
    # 1. Ex 1 end-to-end:
    # list with exact needs oil 5L (fortune_sunlite_oil_5l, lock amazon),
    # surf (surf_excel_matic_fl_liquid_2l, lock amazon), dal (tata_sampann_toor_dal_1kg, lock_platform none).
    # Offer A1 amazon flat 5000 >= 50000 uses 2.
    # POST /lists/{id}/plan -> 200 with plan_run_id.
    # Accept cheapest_now -> baskets created, one per order. Needs -> planned.

    # Create list
    r_list = baskets_client.post("/api/v1/lists", json={"name": "Ex 1 List", "kind": "monthly"})
    assert r_list.status_code == 201, r_list.text
    list_id = r_list.json()["id"]

    # Add needs
    r_oil = baskets_client.post(
        f"/api/v1/lists/{list_id}/needs",
        json={
            "line_id": "oil",
            "product_key": "fortune_sunlite_oil_5l",
            "qty": 1,
            "lock_platform": "amazon",
        },
    )
    assert r_oil.status_code == 201, r_oil.text

    r_surf = baskets_client.post(
        f"/api/v1/lists/{list_id}/needs",
        json={
            "line_id": "surf",
            "product_key": "surf_excel_matic_fl_liquid_2l",
            "qty": 1,
            "lock_platform": "amazon",
        },
    )
    assert r_surf.status_code == 201, r_surf.text

    r_dal = baskets_client.post(
        f"/api/v1/lists/{list_id}/needs",
        json={
            "line_id": "dal",
            "product_key": "tata_sampann_toor_dal_1kg",
            "qty": 1,
        },
    )
    assert r_dal.status_code == 201, r_dal.text

    # Create Offer A1
    r_off = baskets_client.post(
        "/api/v1/offers",
        json={
            "code": "A1",
            "platform": "amazon",
            "kind": "flat",
            "min_order_paise": 50000,
            "value_paise": 5000,
            "uses_left": 2,
        },
    )
    assert r_off.status_code == 201, r_off.text

    # POST /lists/{list_id}/plan
    r_plan = baskets_client.post(f"/api/v1/lists/{list_id}/plan", json={})
    assert r_plan.status_code == 200, r_plan.text
    plan_data = r_plan.json()
    assert "plan_run_id" in plan_data
    plan_run_id = plan_data["plan_run_id"]
    assert "plans" in plan_data

    plans_by_label = {p["label"]: p for p in plan_data["plans"]}
    assert "cheapest_now" in plans_by_label
    cn_plan = plans_by_label["cheapest_now"]
    order_count = len(cn_plan["orders"])
    assert order_count >= 1

    # Accept cheapest_now
    r_accept = baskets_client.post(
        f"/api/v1/plan-runs/{plan_run_id}/accept",
        json={"label": "cheapest_now"},
    )
    assert r_accept.status_code == 200, r_accept.text
    baskets = r_accept.json()
    assert len(baskets) == order_count

    for b in baskets:
        assert b["plan_run_id"] == plan_run_id
        assert b["status"] in {"ready", "pending"}
        assert len(b["lines"]) > 0

    # Verify needs are planned
    r_detail = baskets_client.get(f"/api/v1/lists/{list_id}")
    assert r_detail.status_code == 200
    needs_by_id = {n["line_id"]: n for n in r_detail.json()["needs"]}
    assert needs_by_id["oil"]["status"] == "planned"
    assert needs_by_id["surf"]["status"] == "planned"
    assert needs_by_id["dal"]["status"] == "planned"


def test_2_validation_and_conflict_errors(baskets_client: TestClient) -> None:
    # 2. Accept twice -> 409. Unknown label -> 422. Plan on a list with no open needs -> 422.
    # Empty list
    r_empty = baskets_client.post("/api/v1/lists", json={"name": "Empty List", "kind": "quick"})
    empty_id = r_empty.json()["id"]

    # Plan on list with no open needs -> 422
    r_plan_empty = baskets_client.post(f"/api/v1/lists/{empty_id}/plan", json={})
    assert r_plan_empty.status_code == 422

    # Add need and plan
    r_need = baskets_client.post(
        f"/api/v1/lists/{empty_id}/needs",
        json={"line_id": "oil1", "product_key": "fortune_sunlite_oil_5l", "qty": 1},
    )
    assert r_need.status_code == 201

    r_plan = baskets_client.post(f"/api/v1/lists/{empty_id}/plan", json={})
    assert r_plan.status_code == 200
    plan_run_id = r_plan.json()["plan_run_id"]

    # Unknown label -> 422
    r_unk = baskets_client.post(
        f"/api/v1/plan-runs/{plan_run_id}/accept",
        json={"label": "nonexistent_label"},
    )
    assert r_unk.status_code == 422

    # Valid accept -> 200
    r_acc = baskets_client.post(
        f"/api/v1/plan-runs/{plan_run_id}/accept",
        json={"label": "cheapest_now"},
    )
    assert r_acc.status_code == 200

    # Accept twice -> 409
    r_acc_twice = baskets_client.post(
        f"/api/v1/plan-runs/{plan_run_id}/accept",
        json={"label": "cheapest_now"},
    )
    assert r_acc_twice.status_code == 409


def test_3_place_ready_basket_decrements_offer_and_buys_needs(baskets_client: TestClient) -> None:
    # 3. Place a ready Amazon basket with offer -> status placed.
    # A1 uses_left decremented by the number of placed baskets that applied it. Needs -> bought.
    r_list = baskets_client.post("/api/v1/lists", json={"name": "Place Test", "kind": "quick"})
    list_id = r_list.json()["id"]

    baskets_client.post(
        f"/api/v1/lists/{list_id}/needs",
        json={
            "line_id": "oil",
            "product_key": "fortune_sunlite_oil_5l",
            "qty": 1,
            "lock_platform": "amazon",
        },
    )

    baskets_client.post(
        "/api/v1/offers",
        json={
            "code": "A1",
            "platform": "amazon",
            "kind": "flat",
            "min_order_paise": 50000,
            "value_paise": 5000,
            "uses_left": 2,
        },
    )

    r_plan = baskets_client.post(f"/api/v1/lists/{list_id}/plan", json={})
    assert r_plan.status_code == 200
    plan_run_id = r_plan.json()["plan_run_id"]

    r_acc = baskets_client.post(
        f"/api/v1/plan-runs/{plan_run_id}/accept",
        json={"label": "cheapest_now"},
    )
    assert r_acc.status_code == 200
    baskets = r_acc.json()
    ready_basket = next(b for b in baskets if b["status"] == "ready")
    basket_id = ready_basket["id"]

    # Negative actual_paid_paise -> 422
    r_neg = baskets_client.post(f"/api/v1/baskets/{basket_id}/place", json={"actual_paid_paise": -100})
    assert r_neg.status_code == 422

    # Place basket
    r_place = baskets_client.post(
        f"/api/v1/baskets/{basket_id}/place",
        json={"actual_paid_paise": 61500},
    )
    assert r_place.status_code == 200, r_place.text
    placed_b = r_place.json()
    assert placed_b["status"] == "placed"
    assert placed_b["actual_paid_paise"] == 61500
    assert placed_b["placed_at"] is not None

    # Placing already placed basket -> 409
    r_place_again = baskets_client.post(
        f"/api/v1/baskets/{basket_id}/place",
        json={"actual_paid_paise": 61500},
    )
    assert r_place_again.status_code == 409

    # Check offer uses_left: since A1 was applied on this basket, uses_left should be 1
    r_offers = baskets_client.get("/api/v1/offers")
    assert r_offers.status_code == 200
    a1_off = next(o for o in r_offers.json() if o["code"] == "A1")
    assert a1_off["uses_left"] == 1

    # Check needs -> bought
    r_detail = baskets_client.get(f"/api/v1/lists/{list_id}")
    needs_by_id = {n["line_id"]: n for n in r_detail.json()["needs"]}
    assert needs_by_id["oil"]["status"] == "bought"


def test_4_pending_flow_and_add_lines(baskets_client: TestClient) -> None:
    # 4. Pending flow (Ex 2 shape):
    # needs surf (amazon lock) + oil 5L (amazon lock), fillers = one Amazon seed listing that closes the gap,
    # A1 uses 2 -> accept max_savings (assert it exists) -> one basket pending with shortfall_paise > 0
    # and threshold_paise == 50000.
    # Placing it without without_offer -> 409.
    # Add a line via /lines that lifts the subtotal >= threshold -> status ready, shortfall 0.
    r_list = baskets_client.post("/api/v1/lists", json={"name": "Pending List", "kind": "monthly"})
    list_id = r_list.json()["id"]

    baskets_client.post(
        f"/api/v1/lists/{list_id}/needs",
        json={
            "line_id": "oil",
            "product_key": "fortune_sunlite_oil_5l",
            "qty": 1,
            "lock_platform": "amazon",
        },
    )
    baskets_client.post(
        f"/api/v1/lists/{list_id}/needs",
        json={
            "line_id": "surf",
            "product_key": "surf_excel_matic_fl_liquid_2l",
            "qty": 1,
            "lock_platform": "amazon",
        },
    )

    baskets_client.post(
        "/api/v1/offers",
        json={
            "code": "A1",
            "platform": "amazon",
            "kind": "flat",
            "min_order_paise": 50000,
            "value_paise": 5000,
            "uses_left": 2,
        },
    )

    filler_listing = _get_amazon_filler()

    r_plan = baskets_client.post(
        f"/api/v1/lists/{list_id}/plan",
        json={
            "fillers": [
                {
                    "filler_id": "vim_filler",
                    "listing_id": filler_listing.id,
                    "score": 10,
                }
            ],
            "max_filler_gap_paise": 25000,
        },
    )
    assert r_plan.status_code == 200, r_plan.text
    plan_run_id = r_plan.json()["plan_run_id"]

    r_acc = baskets_client.post(
        f"/api/v1/plan-runs/{plan_run_id}/accept",
        json={"label": "max_savings"},
    )
    assert r_acc.status_code == 200, r_acc.text
    baskets = r_acc.json()

    pending_basket = next(b for b in baskets if b["status"] == "pending")
    assert pending_basket["shortfall_paise"] is not None
    assert pending_basket["shortfall_paise"] > 0
    assert pending_basket["threshold_paise"] == 50000
    pending_id = pending_basket["id"]

    # Placing without without_offer -> 409
    r_place_err = baskets_client.post(
        f"/api/v1/baskets/{pending_id}/place",
        json={"actual_paid_paise": 50000},
    )
    assert r_place_err.status_code == 409

    # Add line via POST /baskets/{id}/lines
    r_add_line = baskets_client.post(
        f"/api/v1/baskets/{pending_id}/lines",
        json={"listing_id": filler_listing.id, "line_id": "extra_vim"},
    )
    assert r_add_line.status_code == 200, r_add_line.text
    updated_b = r_add_line.json()
    assert updated_b["status"] == "ready"
    assert updated_b["shortfall_paise"] == 0
    # Line was added
    assert any(line["line_id"] == "extra_vim" for line in updated_b["lines"])


def test_5_release_pending_basket(baskets_client: TestClient) -> None:
    # 5. Release a pending basket -> released, needs back to open. Release a ready basket -> 409.
    r_list = baskets_client.post("/api/v1/lists", json={"name": "Release Test", "kind": "monthly"})
    list_id = r_list.json()["id"]

    baskets_client.post(
        f"/api/v1/lists/{list_id}/needs",
        json={
            "line_id": "oil",
            "product_key": "fortune_sunlite_oil_5l",
            "qty": 1,
            "lock_platform": "amazon",
        },
    )
    baskets_client.post(
        f"/api/v1/lists/{list_id}/needs",
        json={
            "line_id": "surf",
            "product_key": "surf_excel_matic_fl_liquid_2l",
            "qty": 1,
            "lock_platform": "amazon",
        },
    )

    baskets_client.post(
        "/api/v1/offers",
        json={
            "code": "A1",
            "platform": "amazon",
            "kind": "flat",
            "min_order_paise": 50000,
            "value_paise": 5000,
            "uses_left": 2,
        },
    )

    filler_listing = _get_amazon_filler()

    r_plan = baskets_client.post(
        f"/api/v1/lists/{list_id}/plan",
        json={
            "fillers": [
                {
                    "filler_id": "vim_filler",
                    "listing_id": filler_listing.id,
                    "score": 10,
                }
            ],
            "max_filler_gap_paise": 25000,
        },
    )
    plan_run_id = r_plan.json()["plan_run_id"]

    r_acc = baskets_client.post(
        f"/api/v1/plan-runs/{plan_run_id}/accept",
        json={"label": "max_savings"},
    )
    baskets = r_acc.json()
    pending_basket = next(b for b in baskets if b["status"] == "pending")
    ready_basket = next(b for b in baskets if b["status"] == "ready")

    # Release ready basket -> 409
    r_rel_ready = baskets_client.post(f"/api/v1/baskets/{ready_basket['id']}/release")
    assert r_rel_ready.status_code == 409

    # Release pending basket -> 200
    r_rel_pending = baskets_client.post(f"/api/v1/baskets/{pending_basket['id']}/release")
    assert r_rel_pending.status_code == 200
    assert r_rel_pending.json()["status"] == "released"

    # Needs on pending basket (surf) back to open
    r_detail = baskets_client.get(f"/api/v1/lists/{list_id}")
    needs_by_id = {n["line_id"]: n for n in r_detail.json()["needs"]}
    assert needs_by_id["surf"]["status"] == "open"
    # Oil was on ready basket -> still planned
    assert needs_by_id["oil"]["status"] == "planned"


def test_6_place_pending_with_without_offer(baskets_client: TestClient) -> None:
    # 6. Place pending with without_offer: true -> placed, offer_value_expected_paise == 0, A1 unchanged.
    r_list = baskets_client.post("/api/v1/lists", json={"name": "Without Offer Test", "kind": "monthly"})
    list_id = r_list.json()["id"]

    baskets_client.post(
        f"/api/v1/lists/{list_id}/needs",
        json={
            "line_id": "oil",
            "product_key": "fortune_sunlite_oil_5l",
            "qty": 1,
            "lock_platform": "amazon",
        },
    )
    baskets_client.post(
        f"/api/v1/lists/{list_id}/needs",
        json={
            "line_id": "surf",
            "product_key": "surf_excel_matic_fl_liquid_2l",
            "qty": 1,
            "lock_platform": "amazon",
        },
    )

    baskets_client.post(
        "/api/v1/offers",
        json={
            "code": "A1",
            "platform": "amazon",
            "kind": "flat",
            "min_order_paise": 50000,
            "value_paise": 5000,
            "uses_left": 2,
        },
    )

    filler_listing = _get_amazon_filler()

    r_plan = baskets_client.post(
        f"/api/v1/lists/{list_id}/plan",
        json={
            "fillers": [
                {
                    "filler_id": "vim_filler",
                    "listing_id": filler_listing.id,
                    "score": 10,
                }
            ],
            "max_filler_gap_paise": 25000,
        },
    )
    plan_run_id = r_plan.json()["plan_run_id"]

    r_acc = baskets_client.post(
        f"/api/v1/plan-runs/{plan_run_id}/accept",
        json={"label": "max_savings"},
    )
    baskets = r_acc.json()
    pending_basket = next(b for b in baskets if b["status"] == "pending")

    # Place pending with without_offer: true
    r_place = baskets_client.post(
        f"/api/v1/baskets/{pending_basket['id']}/place",
        json={"actual_paid_paise": 34400, "without_offer": True},
    )
    assert r_place.status_code == 200, r_place.text
    b_data = r_place.json()
    assert b_data["status"] == "placed"
    assert b_data["offer_value_expected_paise"] == 0

    # A1 uses_left unchanged (still 2)
    r_offers = baskets_client.get("/api/v1/offers")
    a1_off = next(o for o in r_offers.json() if o["code"] == "A1")
    assert a1_off["uses_left"] == 2


def test_7_cashback_flow(baskets_client: TestClient) -> None:
    # 7. Cashback: placed -> settled with received amount. Cashback on a ready basket -> 409.
    r_list = baskets_client.post("/api/v1/lists", json={"name": "Cashback Test", "kind": "quick"})
    list_id = r_list.json()["id"]

    baskets_client.post(
        f"/api/v1/lists/{list_id}/needs",
        json={"line_id": "oil", "product_key": "fortune_sunlite_oil_5l", "qty": 1},
    )

    r_plan = baskets_client.post(f"/api/v1/lists/{list_id}/plan", json={})
    plan_run_id = r_plan.json()["plan_run_id"]

    r_acc = baskets_client.post(
        f"/api/v1/plan-runs/{plan_run_id}/accept",
        json={"label": "cheapest_now"},
    )
    baskets = r_acc.json()
    ready_basket = baskets[0]
    basket_id = ready_basket["id"]

    # Cashback on ready basket -> 409
    r_cb_ready = baskets_client.post(f"/api/v1/baskets/{basket_id}/cashback", json={"received_paise": 5000})
    assert r_cb_ready.status_code == 409

    # Place basket
    r_place = baskets_client.post(f"/api/v1/baskets/{basket_id}/place", json={"actual_paid_paise": 61500})
    assert r_place.status_code == 200

    # Cashback on placed basket -> 200
    r_cb = baskets_client.post(f"/api/v1/baskets/{basket_id}/cashback", json={"received_paise": 5000})
    assert r_cb.status_code == 200, r_cb.text
    settled_b = r_cb.json()
    assert settled_b["status"] == "settled"
    assert settled_b["offer_value_received_paise"] == 5000
    assert settled_b["settled_at"] is not None


def test_8_ledger_summary(baskets_client: TestClient) -> None:
    # 8. Ledger: freeze the clock at 2026-10-20. Two baskets placed
    # (paid 61500 and 49300, expected 5000 each), one settled with 5000 ->
    # {placed_count 2, paid 110800, offer_expected 10000, offer_received 5000, cashback_pending 5000}.
    # A different month -> zeros.
    frozen_dt = datetime(2026, 10, 20, 10, 0, 0, tzinfo=UTC)
    baskets_client.app.dependency_overrides[clock.now] = lambda: frozen_dt

    # Basket 1: placed and settled
    r_list1 = baskets_client.post("/api/v1/lists", json={"name": "L1", "kind": "quick"})
    list1_id = r_list1.json()["id"]
    baskets_client.post(
        f"/api/v1/lists/{list1_id}/needs",
        json={
            "line_id": "oil",
            "product_key": "fortune_sunlite_oil_5l",
            "qty": 1,
            "lock_platform": "amazon",
        },
    )
    baskets_client.post(
        "/api/v1/offers",
        json={
            "code": "A1",
            "platform": "amazon",
            "kind": "flat",
            "min_order_paise": 50000,
            "value_paise": 5000,
            "uses_left": 2,
        },
    )
    r_plan1 = baskets_client.post(f"/api/v1/lists/{list1_id}/plan", json={})
    p_id1 = r_plan1.json()["plan_run_id"]
    r_acc1 = baskets_client.post(f"/api/v1/plan-runs/{p_id1}/accept", json={"label": "cheapest_now"})
    b1_id = r_acc1.json()[0]["id"]
    baskets_client.post(f"/api/v1/baskets/{b1_id}/place", json={"actual_paid_paise": 61500})
    baskets_client.post(f"/api/v1/baskets/{b1_id}/cashback", json={"received_paise": 5000})

    # Basket 2: placed but not settled
    r_list2 = baskets_client.post("/api/v1/lists", json={"name": "L2", "kind": "quick"})
    list2_id = r_list2.json()["id"]
    baskets_client.post(
        f"/api/v1/lists/{list2_id}/needs",
        json={
            "line_id": "oil2",
            "product_key": "fortune_sunlite_oil_5l",
            "qty": 1,
            "lock_platform": "amazon",
        },
    )
    r_plan2 = baskets_client.post(f"/api/v1/lists/{list2_id}/plan", json={})
    p_id2 = r_plan2.json()["plan_run_id"]
    r_acc2 = baskets_client.post(f"/api/v1/plan-runs/{p_id2}/accept", json={"label": "cheapest_now"})
    b2_id = r_acc2.json()[0]["id"]
    baskets_client.post(f"/api/v1/baskets/{b2_id}/place", json={"actual_paid_paise": 49300})

    # Query summary for 2026-10
    r_sum = baskets_client.get("/api/v1/ledger/summary?month=2026-10")
    assert r_sum.status_code == 200, r_sum.text
    summary = r_sum.json()
    assert summary["placed_count"] == 2
    assert summary["paid_paise"] == 110800
    assert summary["offer_expected_paise"] == 10000
    assert summary["offer_received_paise"] == 5000
    assert summary["cashback_pending_paise"] == 5000

    # Default month (frozen_dt is in 2026-10)
    r_sum_default = baskets_client.get("/api/v1/ledger/summary")
    assert r_sum_default.status_code == 200
    assert r_sum_default.json() == summary

    # Query summary for a different month (2026-09)
    r_sum_sep = baskets_client.get("/api/v1/ledger/summary?month=2026-09")
    assert r_sum_sep.status_code == 200
    assert r_sum_sep.json() == {
        "placed_count": 0,
        "paid_paise": 0,
        "offer_expected_paise": 0,
        "offer_received_paise": 0,
        "cashback_pending_paise": 0,
    }


def test_9_expired_offer_not_used_in_plan(baskets_client: TestClient) -> None:
    # 9. Expired offer (valid_to yesterday by the frozen clock) is not used in POST /lists/{id}/plan.
    frozen_dt = datetime(2026, 10, 20, 10, 0, 0, tzinfo=UTC)
    baskets_client.app.dependency_overrides[clock.now] = lambda: frozen_dt

    # Expired offer valid_to = 2026-10-19
    baskets_client.post(
        "/api/v1/offers",
        json={
            "code": "EXP1",
            "platform": "amazon",
            "kind": "flat",
            "min_order_paise": 50000,
            "value_paise": 5000,
            "uses_left": 2,
            "valid_to": "2026-10-19",
        },
    )

    r_list = baskets_client.post("/api/v1/lists", json={"name": "Expired Test", "kind": "quick"})
    list_id = r_list.json()["id"]
    baskets_client.post(
        f"/api/v1/lists/{list_id}/needs",
        json={"line_id": "oil", "product_key": "fortune_sunlite_oil_5l", "qty": 1, "lock_platform": "amazon"},
    )

    r_plan = baskets_client.post(f"/api/v1/lists/{list_id}/plan", json={})
    assert r_plan.status_code == 200
    # Check that EXP1 was not applied to any plan
    for plan in r_plan.json()["plans"]:
        for order in plan["orders"]:
            applied_ids = [a["offer_id"] for a in order["offers_applied"]]
            assert "EXP1" not in applied_ids


def test_10_get_baskets_list_and_detail(baskets_client: TestClient) -> None:
    # Test GET /baskets and GET /baskets/{id}
    r_list = baskets_client.post("/api/v1/lists", json={"name": "Fetch Test", "kind": "quick"})
    list_id = r_list.json()["id"]
    baskets_client.post(
        f"/api/v1/lists/{list_id}/needs",
        json={"line_id": "oil", "product_key": "fortune_sunlite_oil_5l", "qty": 1},
    )

    r_plan = baskets_client.post(f"/api/v1/lists/{list_id}/plan", json={})
    plan_run_id = r_plan.json()["plan_run_id"]

    r_acc = baskets_client.post(f"/api/v1/plan-runs/{plan_run_id}/accept", json={"label": "cheapest_now"})
    baskets = r_acc.json()
    basket_id = baskets[0]["id"]

    # GET /baskets
    r_all = baskets_client.get("/api/v1/baskets")
    assert r_all.status_code == 200
    all_baskets = r_all.json()
    assert any(b["id"] == basket_id for b in all_baskets)

    # Filter by status
    r_ready = baskets_client.get("/api/v1/baskets?status=ready")
    assert r_ready.status_code == 200
    assert all(b["status"] == "ready" for b in r_ready.json())

    r_pending = baskets_client.get("/api/v1/baskets?status=pending")
    assert r_pending.status_code == 200
    assert all(b["status"] == "pending" for b in r_pending.json())

    # GET /baskets/{id}
    r_one = baskets_client.get(f"/api/v1/baskets/{basket_id}")
    assert r_one.status_code == 200
    assert r_one.json()["id"] == basket_id
    assert len(r_one.json()["lines"]) > 0

    # Unknown basket -> 404
    assert baskets_client.get("/api/v1/baskets/999999").status_code == 404
