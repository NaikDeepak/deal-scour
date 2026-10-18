from collections.abc import Generator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlmodel import Session

from app.api.v1.plans import router
from app.core.db import get_session
from app.domain.catalog import load_seed
from app.optimizer.contract import Offer
from app.optimizer.planning import Candidate, NeedLine
from app.optimizer.planset import plan
from app.pricing.fee_schedules import Platform
from app.pricing.landed import unit_price

app = FastAPI()
app.include_router(router, prefix="/api/v1")
client = TestClient(app)


@pytest.fixture(autouse=True)
def _setup_db(engine: Engine) -> Generator[None, None, None]:
    def override_get_session() -> Generator[Session, None, None]:
        with Session(engine) as s:
            yield s

    app.dependency_overrides[get_session] = override_get_session
    yield
    app.dependency_overrides.clear()


def test_1_minimal_atta() -> None:
    # 1. Minimal: needs [atta] (aashirvaad_select_atta_5kg), default members, no offers -> 200.
    # Cheapest now has 1 order on instamart with unit_price_paise == 27700, fees.total == 0
    # (Swiggy One member and 27700 >= the member free-delivery minimum of 19900), net_paise == 27700.
    # Baseline is equal. One plan (cheapest_now). savings_vs_baseline_paise == 0.
    resp = client.post(
        "/api/v1/plans",
        json={
            "needs": [{"line_id": "atta", "product_key": "aashirvaad_select_atta_5kg", "qty": 1}],
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    # Baseline assertions
    baseline = data["baseline"]
    assert baseline["total_net_paise"] == 27700
    assert len(baseline["orders"]) == 1
    base_order = baseline["orders"][0]
    assert base_order["platform"] == "instamart"
    assert base_order["status"] == "now"
    assert base_order["net_paise"] == 27700
    assert base_order["fees"]["total"] == 0

    # Plans assertions
    plans = {p["label"]: p for p in data["plans"]}
    assert "cheapest_now" in plans
    cn = plans["cheapest_now"]
    assert cn["label"] == "cheapest_now"
    assert cn["savings_vs_baseline_paise"] == 0
    assert cn["effective_cost_paise"] == 27700
    assert cn["total_net_paise"] == 27700

    assert len(cn["orders"]) == 1
    cn_order = cn["orders"][0]
    assert cn_order["platform"] == "instamart"
    assert cn_order["status"] == "now"
    assert cn_order["fees"]["total"] == 0
    assert cn_order["net_paise"] == 27700

    assert len(cn_order["lines"]) == 1
    line = cn_order["lines"][0]
    assert line["line_id"] == "atta"
    assert line["unit_price_paise"] == 27700
    assert line["packs"] == 1
    assert line["line_total_paise"] == 27700
    assert "qty" not in line
    assert line["is_filler"] is False
    assert line["title"] != ""
    assert line["pack_label"] != ""


def test_2_members_blinkit() -> None:
    # 2. members=["blinkit"] -> atta on blinkit at 27700, delivery 0 (Gold member).
    resp = client.post(
        "/api/v1/plans",
        json={
            "members": ["blinkit"],
            "needs": [{"line_id": "atta", "product_key": "aashirvaad_select_atta_5kg", "qty": 1}],
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    plans = {p["label"]: p for p in data["plans"]}
    cn = plans["cheapest_now"]
    assert len(cn["orders"]) == 1
    order = cn["orders"][0]
    assert order["platform"] == "blinkit"
    assert order["lines"][0]["unit_price_paise"] == 27700
    assert order["lines"][0]["packs"] == 1
    assert order["lines"][0]["line_total_paise"] == 27700
    assert "qty" not in order["lines"][0]
    assert order["fees"]["delivery"] == 0
    assert order["net_paise"] == 27700


def test_3_consistency_with_direct_optimizer_call() -> None:
    # 3. Consistency: for the request in case 5, every number in the response equals
    # what optimizer.planset.plan(...) returns when called directly with mapped inputs.
    req_body = {
        "needs": [
            {"line_id": "oil", "product_key": "fortune_sunlite_oil_5l", "qty": 1},
            {"line_id": "surf", "product_key": "surf_excel_matic_fl_liquid_2l", "qty": 1},
            {"line_id": "almonds", "product_key": "happilo_almonds_1kg", "qty": 1},
            {"line_id": "ghee", "product_key": "amul_cow_ghee_1l", "qty": 1},
        ],
        "offers": [
            {
                "id": "A1",
                "platform": "amazon",
                "kind": "flat",
                "min_order_paise": 50000,
                "value_paise": 5000,
                "uses_left": 2,
            }
        ],
    }
    resp = client.post("/api/v1/plans", json=req_body)
    assert resp.status_code == 200, resp.text
    api_data = resp.json()

    # Build direct optimizer inputs
    seed = load_seed()
    seed_by_prod: dict[str, list[Any]] = {}
    for item in seed:
        seed_by_prod.setdefault(item.product_key, []).append(item)

    default_members = {"amazon", "instamart", "flipkart"}
    all_platforms: list[Platform] = ["amazon", "flipkart", "blinkit", "instamart", "zepto"]
    memberships = {p: p in default_members for p in all_platforms}

    opt_needs: list[NeedLine] = []
    need_items: list[dict[str, Any]] = req_body["needs"]  # type: ignore[assignment]
    for need_item in need_items:
        prod_listings = seed_by_prod[str(need_item["product_key"])]
        cands = [
            Candidate(
                listing_id=item.id,
                platform=item.platform,
                unit_price=unit_price(item.item_price(), item.platform in default_members),
                eta_minutes=item.eta_minutes,
            )
            for item in prod_listings
        ]
        opt_needs.append(
            NeedLine(
                line_id=str(need_item["line_id"]),
                category=prod_listings[0].category,
                qty=int(need_item["qty"]),
                candidates=tuple(cands),
            )
        )

    opt_offers = [
        Offer(
            id="A1",
            platform="amazon",
            kind="flat",
            min_order=50000,
            value=5000,
            uses_left=2,
        )
    ]

    direct_planset = plan(
        needs=opt_needs,
        offers=opt_offers,
        memberships=memberships,
    )

    # Compare baseline
    assert api_data["baseline"]["total_net_paise"] == direct_planset.baseline.result.total_net
    assert api_data["baseline"]["total_subtotal_paise"] == direct_planset.baseline.result.total_subtotal
    assert api_data["baseline"]["total_fees_paise"] == direct_planset.baseline.result.total_fees
    assert api_data["baseline"]["total_offer_value_paise"] == direct_planset.baseline.result.total_offer_value

    for api_order, direct_order_res in zip(
        api_data["baseline"]["orders"], direct_planset.baseline.result.orders, strict=True
    ):
        assert api_order["platform"] == direct_order_res.platform
        assert api_order["subtotal_paise"] == direct_order_res.subtotal
        assert api_order["net_paise"] == direct_order_res.net
        assert api_order["fees"]["total"] == direct_order_res.fees.total

    # Compare plans
    direct_plans_by_label = {p.label: p for p in direct_planset.plans}
    for api_plan in api_data["plans"]:
        label = api_plan["label"]
        assert label in direct_plans_by_label
        direct_p = direct_plans_by_label[label]

        assert api_plan["effective_cost_paise"] == direct_p.effective_cost
        assert api_plan["savings_vs_baseline_paise"] == direct_p.savings_vs_baseline
        assert api_plan["total_net_paise"] == direct_p.plan.result.total_net

        for api_order, direct_order_res in zip(
            api_plan["orders"], direct_p.plan.result.orders, strict=True
        ):
            assert api_order["net_paise"] == direct_order_res.net
            assert api_order["subtotal_paise"] == direct_order_res.subtotal
            assert api_order["fees"]["total"] == direct_order_res.fees.total

        api_reasons_text = [r["text"] for r in api_plan["reasons"]]
        direct_reasons_text = [r.text for r in direct_p.reasons]
        assert api_reasons_text == direct_reasons_text


def test_4_validation_errors() -> None:
    # 4. Unknown product_key -> 422. Duplicate line_id -> 422. Unknown member platform -> 422.
    # qty: 0 -> 422. Unknown filler listing_id -> 422. Offer kind: "flat" & value_paise: 0 -> 422.
    # Unknown product_key
    r = client.post(
        "/api/v1/plans",
        json={"needs": [{"line_id": "x", "product_key": "nonexistent_key", "qty": 1}]},
    )
    assert r.status_code == 422

    # Duplicate line_id
    r = client.post(
        "/api/v1/plans",
        json={
            "needs": [
                {"line_id": "atta", "product_key": "aashirvaad_select_atta_5kg", "qty": 1},
                {"line_id": "atta", "product_key": "fortune_sunlite_oil_5l", "qty": 1},
            ]
        },
    )
    assert r.status_code == 422

    # Unknown member platform
    r = client.post(
        "/api/v1/plans",
        json={
            "members": ["amazon", "grofers_unknown"],
            "needs": [{"line_id": "atta", "product_key": "aashirvaad_select_atta_5kg", "qty": 1}],
        },
    )
    assert r.status_code == 422

    # qty: 0
    r = client.post(
        "/api/v1/plans",
        json={"needs": [{"line_id": "atta", "product_key": "aashirvaad_select_atta_5kg", "qty": 0}]},
    )
    assert r.status_code == 422

    # Unknown filler listing_id
    r = client.post(
        "/api/v1/plans",
        json={
            "needs": [{"line_id": "atta", "product_key": "aashirvaad_select_atta_5kg", "qty": 1}],
            "fillers": [{"filler_id": "f1", "listing_id": "unknown_listing_id", "score": 5}],
        },
    )
    assert r.status_code == 422

    # Offer flat with value_paise == 0
    r = client.post(
        "/api/v1/plans",
        json={
            "needs": [{"line_id": "atta", "product_key": "aashirvaad_select_atta_5kg", "qty": 1}],
            "offers": [
                {
                    "id": "O1",
                    "platform": "amazon",
                    "kind": "flat",
                    "min_order_paise": 50000,
                    "value_paise": 0,
                }
            ],
        },
    )
    assert r.status_code == 422


def test_5_monthly_basket_with_split() -> None:
    # 5. Monthly basket with a split (seed data, default members):
    # needs oil (fortune_sunlite_oil_5l), surf (surf_excel_matic_fl_liquid_2l),
    # almonds (happilo_almonds_1kg), ghee (amul_cow_ghee_1l).
    # Offer A1 amazon flat 5000 >= 50000, uses 2.
    # Assert: 200. Every need is in exactly one order of cheapest_now.
    # cheapest_now.total_net_paise <= baseline.total_net_paise.
    # Reasons are a list of objects with non-empty text.
    resp = client.post(
        "/api/v1/plans",
        json={
            "needs": [
                {"line_id": "oil", "product_key": "fortune_sunlite_oil_5l", "qty": 1},
                {"line_id": "surf", "product_key": "surf_excel_matic_fl_liquid_2l", "qty": 1},
                {"line_id": "almonds", "product_key": "happilo_almonds_1kg", "qty": 1},
                {"line_id": "ghee", "product_key": "amul_cow_ghee_1l", "qty": 1},
            ],
            "offers": [
                {
                    "id": "A1",
                    "platform": "amazon",
                    "kind": "flat",
                    "min_order_paise": 50000,
                    "value_paise": 5000,
                    "uses_left": 2,
                }
            ],
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    baseline = data["baseline"]
    plans = {p["label"]: p for p in data["plans"]}
    assert "cheapest_now" in plans
    cn = plans["cheapest_now"]

    assert cn["total_net_paise"] <= baseline["total_net_paise"]

    # Every need line_id is in exactly one order of cheapest_now
    all_need_ids = {"oil", "surf", "almonds", "ghee"}
    found_lines: list[str] = []
    for order in cn["orders"]:
        for line in order["lines"]:
            if not line["is_filler"]:
                found_lines.append(line["line_id"])
                assert line["packs"] == 1
                assert line["line_total_paise"] == line["unit_price_paise"] * line["packs"]
                assert "qty" not in line
    assert sorted(found_lines) == sorted(all_need_ids)

    # Reasons are non-empty
    for r in cn["reasons"]:
        assert r["text"] != ""
        assert "code" in r
        assert "platform" in r
        assert "amount_paise" in r
        assert "line_ids" in r


def test_6_pending_through_api() -> None:
    # 6. Pending through the API: needs surf (surf_excel_matic_fl_liquid_2l) only, lock_platform: "amazon".
    # A1 uses 2. Fillers: one amazon listing from the seed whose price closes the gap.
    # Assert that if max_savings is present, it has exactly one order with status: "pending",
    # a positive shortfall_paise, and target_offer_id == "A1", and that its filler lines have is_filler: true.
    seed = load_seed()
    surf_amazon = next(
        item
        for item in seed
        if item.product_key == "surf_excel_matic_fl_liquid_2l" and item.platform == "amazon"
    )
    surf_price = unit_price(surf_amazon.item_price(), is_member=True)
    shortfall = 50000 - surf_price

    # Find an amazon filler listing that can close the shortfall
    filler_listing = next(
        item
        for item in seed
        if item.platform == "amazon"
        and item.product_key != "surf_excel_matic_fl_liquid_2l"
        and unit_price(item.item_price(), is_member=True) >= shortfall
        and unit_price(item.item_price(), is_member=True) <= 25000
    )

    resp = client.post(
        "/api/v1/plans",
        json={
            "needs": [
                {
                    "line_id": "surf",
                    "product_key": "surf_excel_matic_fl_liquid_2l",
                    "qty": 1,
                    "lock_platform": "amazon",
                }
            ],
            "offers": [
                {
                    "id": "A1",
                    "platform": "amazon",
                    "kind": "flat",
                    "min_order_paise": 50000,
                    "value_paise": 5000,
                    "uses_left": 2,
                }
            ],
            "fillers": [
                {
                    "filler_id": "test_filler",
                    "listing_id": filler_listing.id,
                    "score": 10,
                }
            ],
            "max_filler_gap_paise": 25000,
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    plans_by_label = {p["label"]: p for p in data["plans"]}
    if "max_savings" in plans_by_label:
        ms = plans_by_label["max_savings"]
        pending_orders = [o for o in ms["orders"] if o["status"] == "pending"]
        assert len(pending_orders) == 1
        pend_order = pending_orders[0]
        assert pend_order["shortfall_paise"] is not None
        assert pend_order["shortfall_paise"] > 0
        assert pend_order["target_offer_id"] == "A1"

        filler_lines = [line for line in pend_order["lines"] if line["is_filler"]]
        assert len(filler_lines) >= 1
        for fl in filler_lines:
            assert fl["line_id"] == "test_filler"
            assert fl["is_filler"] is True
            assert fl["packs"] == 1
            assert fl["line_total_paise"] == fl["unit_price_paise"]
            assert "qty" not in fl
            assert fl["title"] != ""
            assert fl["pack_label"] != ""


def test_7_need_by_minutes_unpriced() -> None:
    # 7. need_by_minutes: 30 on a product with no listing that fast ->
    # that line is in unpriced for every plan.
    seed = load_seed()
    # Find a product whose fastest listing has eta_minutes > 30
    prods: dict[str, list[int]] = {}
    for item in seed:
        prods.setdefault(item.product_key, []).append(item.eta_minutes)

    slow_prod = next(pk for pk, etas in prods.items() if min(etas) > 30)

    resp = client.post(
        "/api/v1/plans",
        json={
            "needs": [
                {
                    "line_id": "slow_item",
                    "product_key": slow_prod,
                    "qty": 1,
                    "need_by_minutes": 30,
                }
            ],
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert "slow_item" in data["baseline"]["unpriced"]
    for plan_item in data["plans"]:
        assert "slow_item" in plan_item["unpriced"]


def test_8_money_fields_are_all_int() -> None:
    # 8. Response money fields are all int (walk the JSON and assert no float anywhere).
    resp = client.post(
        "/api/v1/plans",
        json={
            "needs": [
                {"line_id": "oil", "product_key": "fortune_sunlite_oil_5l", "qty": 1},
                {"line_id": "surf", "product_key": "surf_excel_matic_fl_liquid_2l", "qty": 1},
            ],
            "offers": [
                {
                    "id": "A1",
                    "platform": "amazon",
                    "kind": "flat",
                    "min_order_paise": 50000,
                    "value_paise": 5000,
                    "uses_left": 2,
                }
            ],
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    def assert_no_floats(obj: Any, path: str = "") -> None:
        if isinstance(obj, float):
            raise AssertionError(f"Found float at {path}: {obj}")
        elif isinstance(obj, dict):
            for k, v in obj.items():
                assert_no_floats(v, f"{path}.{k}")
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                assert_no_floats(v, f"{path}[{i}]")

    assert_no_floats(data)


def test_9_tiers_validation() -> None:
    # tiers must be exactly [min, value] pairs at request validation:
    # [[1]] and [[1, 2, 3]] -> 422
    r1 = client.post(
        "/api/v1/plans",
        json={
            "needs": [{"line_id": "atta", "product_key": "aashirvaad_select_atta_5kg", "qty": 1}],
            "offers": [
                {
                    "id": "O1",
                    "platform": "amazon",
                    "kind": "tiered",
                    "tiers": [[1]],
                }
            ],
        },
    )
    assert r1.status_code == 422

    r2 = client.post(
        "/api/v1/plans",
        json={
            "needs": [{"line_id": "atta", "product_key": "aashirvaad_select_atta_5kg", "qty": 1}],
            "offers": [
                {
                    "id": "O1",
                    "platform": "amazon",
                    "kind": "tiered",
                    "tiers": [[1, 2, 3]],
                }
            ],
        },
    )
    assert r2.status_code == 422


def test_10_duplicate_offer_ids_and_optimizer_value_error(monkeypatch: pytest.MonkeyPatch) -> None:
    # 1. Duplicate offer ids rejected at request validation -> 422
    r1 = client.post(
        "/api/v1/plans",
        json={
            "needs": [{"line_id": "atta", "product_key": "aashirvaad_select_atta_5kg", "qty": 1}],
            "offers": [
                {
                    "id": "A1",
                    "platform": "amazon",
                    "kind": "flat",
                    "min_order_paise": 50000,
                    "value_paise": 5000,
                },
                {
                    "id": "A1",
                    "platform": "amazon",
                    "kind": "flat",
                    "min_order_paise": 50000,
                    "value_paise": 5000,
                },
            ],
        },
    )
    assert r1.status_code == 422

    # 2. Any ValueError from optimizer plan(...) wrapped -> 422
    import app.api.v1.plans as plans_module

    def mock_plan(*args: Any, **kwargs: Any) -> Any:
        raise ValueError("simulated optimizer failure")

    monkeypatch.setattr(plans_module, "plan", mock_plan)
    r2 = client.post(
        "/api/v1/plans",
        json={"needs": [{"line_id": "atta", "product_key": "aashirvaad_select_atta_5kg", "qty": 1}]},
    )
    assert r2.status_code == 422
    assert "simulated optimizer failure" in r2.json()["detail"]


def test_11_duplicate_and_conflicting_filler_id() -> None:
    # Duplicate filler_id -> 422
    r1 = client.post(
        "/api/v1/plans",
        json={
            "needs": [{"line_id": "atta", "product_key": "aashirvaad_select_atta_5kg", "qty": 1}],
            "fillers": [
                {"filler_id": "f1", "listing_id": "stp-1", "score": 1},
                {"filler_id": "f1", "listing_id": "stp-2", "score": 2},
            ],
        },
    )
    assert r1.status_code == 422

    # filler_id equal to any need line_id -> 422
    r2 = client.post(
        "/api/v1/plans",
        json={
            "needs": [{"line_id": "atta", "product_key": "aashirvaad_select_atta_5kg", "qty": 1}],
            "fillers": [
                {"filler_id": "atta", "listing_id": "stp-1", "score": 1},
            ],
        },
    )
    assert r2.status_code == 422


def test_12_qty_range_validation() -> None:
    # qty must be 1..99 -> 422 outside that range
    r_zero = client.post(
        "/api/v1/plans",
        json={"needs": [{"line_id": "atta", "product_key": "aashirvaad_select_atta_5kg", "qty": 0}]},
    )
    assert r_zero.status_code == 422

    r_negative = client.post(
        "/api/v1/plans",
        json={"needs": [{"line_id": "atta", "product_key": "aashirvaad_select_atta_5kg", "qty": -1}]},
    )
    assert r_negative.status_code == 422

    r_100 = client.post(
        "/api/v1/plans",
        json={"needs": [{"line_id": "atta", "product_key": "aashirvaad_select_atta_5kg", "qty": 100}]},
    )
    assert r_100.status_code == 422

    r_1 = client.post(
        "/api/v1/plans",
        json={"needs": [{"line_id": "atta", "product_key": "aashirvaad_select_atta_5kg", "qty": 1}]},
    )
    assert r_1.status_code == 200

    r_99 = client.post(
        "/api/v1/plans",
        json={"needs": [{"line_id": "atta", "product_key": "aashirvaad_select_atta_5kg", "qty": 99}]},
    )
    assert r_99.status_code == 200


def test_regression_case_4_exact_5l_oil() -> None:
    # 4. Regression (the bug): exact need fortune_sunlite_oil_5l -> cheapest_now line
    # listing_id == "stp-4", packs == 1, line_total_paise == 66500. No plan ever contains stp-6.
    resp = client.post(
        "/api/v1/plans",
        json={
            "needs": [{"line_id": "oil", "product_key": "fortune_sunlite_oil_5l", "qty": 1}],
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    for p in data["plans"]:
        for order in p["orders"]:
            for line in order["lines"]:
                assert line["listing_id"] != "stp-6", f"Plan {p['label']} contained 1L pouch stp-6!"

    cn = next(p for p in data["plans"] if p["label"] == "cheapest_now")
    oil_line = cn["orders"][0]["lines"][0]
    assert oil_line["listing_id"] == "stp-4"
    assert oil_line["packs"] == 1
    assert oil_line["unit_price_paise"] == 66500
    assert oil_line["line_total_paise"] == 66500


def test_case_5_flexible_sunflower_oil() -> None:
    # 5. Flexible sunflower_oil, quantity "5L" -> stp-4, 66500.
    # With lock_platform: "zepto" -> stp-6, packs 5, unit_price_paise 14200, line_total_paise 71000.
    r1 = client.post(
        "/api/v1/plans",
        json={
            "needs": [{"line_id": "oil", "family_key": "sunflower_oil", "quantity": "5L", "qty": 1}],
        },
    )
    assert r1.status_code == 200, r1.text
    cn1 = next(p for p in r1.json()["plans"] if p["label"] == "cheapest_now")
    line1 = cn1["orders"][0]["lines"][0]
    assert line1["listing_id"] == "stp-4"
    assert line1["packs"] == 1
    assert line1["unit_price_paise"] == 66500
    assert line1["line_total_paise"] == 66500

    r2 = client.post(
        "/api/v1/plans",
        json={
            "needs": [
                {
                    "line_id": "oil",
                    "family_key": "sunflower_oil",
                    "quantity": "5L",
                    "qty": 1,
                    "lock_platform": "zepto",
                }
            ],
        },
    )
    assert r2.status_code == 200, r2.text
    cn2 = next(p for p in r2.json()["plans"] if p["label"] == "cheapest_now")
    line2 = cn2["orders"][0]["lines"][0]
    assert line2["listing_id"] == "stp-6"
    assert line2["packs"] == 5
    assert line2["unit_price_paise"] == 14200
    assert line2["line_total_paise"] == 71000


def test_case_6_flexible_almonds_with_eta() -> None:
    # 6. Flexible almonds, quantity "1kg" -> alm-1 (61900).
    # With need_by_minutes: 30 -> alm-2 (instamart, eta 14), packs 2, line_total_paise 80000.
    r1 = client.post(
        "/api/v1/plans",
        json={
            "needs": [{"line_id": "alm", "family_key": "almonds", "quantity": "1kg", "qty": 1}],
        },
    )
    assert r1.status_code == 200, r1.text
    cn1 = next(p for p in r1.json()["plans"] if p["label"] == "cheapest_now")
    line1 = cn1["orders"][0]["lines"][0]
    assert line1["listing_id"] == "alm-1"
    assert line1["packs"] == 1
    assert line1["unit_price_paise"] == 61900
    assert line1["line_total_paise"] == 61900

    r2 = client.post(
        "/api/v1/plans",
        json={
            "needs": [
                {
                    "line_id": "alm",
                    "family_key": "almonds",
                    "quantity": "1kg",
                    "qty": 1,
                    "need_by_minutes": 30,
                }
            ],
        },
    )
    assert r2.status_code == 200, r2.text
    cn2 = next(p for p in r2.json()["plans"] if p["label"] == "cheapest_now")
    line2 = cn2["orders"][0]["lines"][0]
    assert line2["listing_id"] == "alm-2"
    assert line2["packs"] == 2
    assert line2["unit_price_paise"] == 40000
    assert line2["line_total_paise"] == 80000


def test_case_7_round_up_tea() -> None:
    # 7. Round-up: flexible tea, quantity "1.5kg" -> bev-2 (500 g × 3 = 71100) beats bev-1 (1 kg × 2 = 92000).
    resp = client.post(
        "/api/v1/plans",
        json={
            "needs": [{"line_id": "tea", "family_key": "tea", "quantity": "1.5kg", "qty": 1}],
        },
    )
    assert resp.status_code == 200, resp.text
    cn = next(p for p in resp.json()["plans"] if p["label"] == "cheapest_now")
    line = cn["orders"][0]["lines"][0]
    assert line["listing_id"] == "bev-2"
    assert line["packs"] == 3
    assert line["unit_price_paise"] == 23700
    assert line["line_total_paise"] == 71100


def test_case_8_qty_multiplies_target_tea() -> None:
    # 8. qty multiplies the target: flexible tea, quantity "500g", qty 2 -> target 1000 g ->
    # bev-1 (46000) beats bev-2 × 2 (47400).
    resp = client.post(
        "/api/v1/plans",
        json={
            "needs": [{"line_id": "tea", "family_key": "tea", "quantity": "500g", "qty": 2}],
        },
    )
    assert resp.status_code == 200, resp.text
    cn = next(p for p in resp.json()["plans"] if p["label"] == "cheapest_now")
    line = cn["orders"][0]["lines"][0]
    assert line["listing_id"] == "bev-1"
    assert line["packs"] == 1
    assert line["unit_price_paise"] == 46000
    assert line["line_total_paise"] == 46000


def test_case_9_validation_422s() -> None:
    # 9. 422s: both keys set. Neither key set. Flexible without quantity. Exact with quantity.
    # quantity "5kg" for sunflower_oil (unit mismatch). quantity "lots". Unknown family.
    # The old key "fortune_oil" as a product_key.

    # Both keys set
    r = client.post(
        "/api/v1/plans",
        json={
            "needs": [
                {
                    "line_id": "oil",
                    "product_key": "fortune_sunlite_oil_5l",
                    "family_key": "sunflower_oil",
                }
            ]
        },
    )
    assert r.status_code == 422

    # Neither key set
    r = client.post(
        "/api/v1/plans",
        json={"needs": [{"line_id": "oil"}]},
    )
    assert r.status_code == 422

    # Flexible without quantity
    r = client.post(
        "/api/v1/plans",
        json={"needs": [{"line_id": "oil", "family_key": "sunflower_oil"}]},
    )
    assert r.status_code == 422

    # Exact with quantity
    r = client.post(
        "/api/v1/plans",
        json={
            "needs": [
                {"line_id": "oil", "product_key": "fortune_sunlite_oil_5l", "quantity": "5L"}
            ]
        },
    )
    assert r.status_code == 422

    # quantity "5kg" for sunflower_oil (unit mismatch) -> 422 naming the family
    r = client.post(
        "/api/v1/plans",
        json={
            "needs": [
                {"line_id": "oil", "family_key": "sunflower_oil", "quantity": "5kg"}
            ]
        },
    )
    assert r.status_code == 422
    assert "sunflower_oil" in r.json()["detail"]

    # quantity "lots" (unparseable)
    r = client.post(
        "/api/v1/plans",
        json={
            "needs": [
                {"line_id": "oil", "family_key": "sunflower_oil", "quantity": "lots"}
            ]
        },
    )
    assert r.status_code == 422

    # Unknown family
    r = client.post(
        "/api/v1/plans",
        json={
            "needs": [
                {"line_id": "oil", "family_key": "unknown_oil_family", "quantity": "1L"}
            ]
        },
    )
    assert r.status_code == 422

    # Old key "fortune_oil" as a product_key
    r = client.post(
        "/api/v1/plans",
        json={"needs": [{"line_id": "oil", "product_key": "fortune_oil"}]},
    )
    assert r.status_code == 422


def test_case_10_response_lines_contract() -> None:
    # 10. Every response line: line_total_paise == unit_price_paise * packs. All money is int.
    # Filler lines have packs == 1.
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
        and item.product_key != "surf_excel_matic_fl_liquid_2l"
        and unit_price(item.item_price(), is_member=True) >= shortfall
        and unit_price(item.item_price(), is_member=True) <= 25000
    )

    resp = client.post(
        "/api/v1/plans",
        json={
            "needs": [
                {"line_id": "exact_oil", "product_key": "fortune_sunlite_oil_5l", "qty": 2},
                {"line_id": "flex_oil", "family_key": "sunflower_oil", "quantity": "5L", "qty": 1},
                {
                    "line_id": "surf",
                    "product_key": "surf_excel_matic_fl_liquid_2l",
                    "qty": 1,
                    "lock_platform": "amazon",
                },
            ],
            "offers": [
                {
                    "id": "A1",
                    "platform": "amazon",
                    "kind": "flat",
                    "min_order_paise": 50000,
                    "value_paise": 5000,
                    "uses_left": 2,
                }
            ],
            "fillers": [
                {
                    "filler_id": "test_filler",
                    "listing_id": filler_listing.id,
                    "score": 10,
                }
            ],
            "max_filler_gap_paise": 25000,
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    for p in [data["baseline"]] + data["plans"]:
        for order in p["orders"]:
            for line in order["lines"]:
                assert isinstance(line["packs"], int)
                assert isinstance(line["unit_price_paise"], int)
                assert isinstance(line["line_total_paise"], int)
                assert line["line_total_paise"] == line["unit_price_paise"] * line["packs"]
                if line["is_filler"]:
                    assert line["packs"] == 1


def test_flexible_quantity_too_large_is_422_not_500(engine: Engine) -> None:
    from fastapi import FastAPI

    from app.api.v1 import plans

    test_app = FastAPI()
    test_app.include_router(plans.router, prefix="/api/v1")

    def override_get_session() -> Generator[Session, None, None]:
        with Session(engine) as s:
            yield s

    test_app.dependency_overrides[get_session] = override_get_session
    c = TestClient(test_app, raise_server_exceptions=False)
    huge = "1" + "0" * 309 + "L"
    for quantity in (huge, "101L", "100001g"):
        body = {"needs": [{"line_id": "oil", "family_key": "sunflower_oil", "quantity": quantity}]}
        assert c.post("/api/v1/plans", json=body).status_code == 422, quantity
    ok = {"needs": [{"line_id": "oil", "family_key": "sunflower_oil", "quantity": "100L"}]}
    assert c.post("/api/v1/plans", json=ok).status_code == 200
