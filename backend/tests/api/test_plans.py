from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.plans import router
from app.domain.catalog import load_seed
from app.optimizer.contract import Offer
from app.optimizer.planning import Candidate, NeedLine
from app.optimizer.planset import plan
from app.pricing.fee_schedules import Platform
from app.pricing.landed import unit_price

app = FastAPI()
app.include_router(router, prefix="/api/v1")
client = TestClient(app)


def test_1_minimal_atta() -> None:
    # 1. Minimal: needs [atta] (aashirvaad_atta), default members, no offers -> 200.
    # Cheapest now has 1 order on instamart with unit_price_paise == 27700, fees.total == 0
    # (Swiggy One member and 27700 >= the member free-delivery minimum of 19900), net_paise == 27700.
    # Baseline is equal. One plan (cheapest_now). savings_vs_baseline_paise == 0.
    resp = client.post(
        "/api/v1/plans",
        json={
            "needs": [{"line_id": "atta", "product_key": "aashirvaad_atta", "qty": 1}],
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
    assert line["qty"] == 1
    assert line["is_filler"] is False
    assert line["title"] != ""
    assert line["pack_label"] != ""


def test_2_members_blinkit() -> None:
    # 2. members=["blinkit"] -> atta on blinkit at 27700, delivery 0 (Gold member).
    resp = client.post(
        "/api/v1/plans",
        json={
            "members": ["blinkit"],
            "needs": [{"line_id": "atta", "product_key": "aashirvaad_atta", "qty": 1}],
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
    assert order["fees"]["delivery"] == 0
    assert order["net_paise"] == 27700


def test_3_consistency_with_direct_optimizer_call() -> None:
    # 3. Consistency: for the request in case 5, every number in the response equals
    # what optimizer.planset.plan(...) returns when called directly with mapped inputs.
    req_body = {
        "needs": [
            {"line_id": "oil", "product_key": "fortune_oil", "qty": 1},
            {"line_id": "surf", "product_key": "surf_liquid", "qty": 1},
            {"line_id": "almonds", "product_key": "california_almonds", "qty": 1},
            {"line_id": "ghee", "product_key": "amul_ghee", "qty": 1},
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
    for need_item in req_body["needs"]:
        prod_listings = seed_by_prod[need_item["product_key"]]
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
                line_id=need_item["line_id"],
                category=prod_listings[0].category,
                qty=need_item["qty"],
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
                {"line_id": "atta", "product_key": "aashirvaad_atta", "qty": 1},
                {"line_id": "atta", "product_key": "fortune_oil", "qty": 1},
            ]
        },
    )
    assert r.status_code == 422

    # Unknown member platform
    r = client.post(
        "/api/v1/plans",
        json={
            "members": ["amazon", "grofers_unknown"],
            "needs": [{"line_id": "atta", "product_key": "aashirvaad_atta", "qty": 1}],
        },
    )
    assert r.status_code == 422

    # qty: 0
    r = client.post(
        "/api/v1/plans",
        json={"needs": [{"line_id": "atta", "product_key": "aashirvaad_atta", "qty": 0}]},
    )
    assert r.status_code == 422

    # Unknown filler listing_id
    r = client.post(
        "/api/v1/plans",
        json={
            "needs": [{"line_id": "atta", "product_key": "aashirvaad_atta", "qty": 1}],
            "fillers": [{"filler_id": "f1", "listing_id": "unknown_listing_id", "score": 5}],
        },
    )
    assert r.status_code == 422

    # Offer flat with value_paise == 0
    r = client.post(
        "/api/v1/plans",
        json={
            "needs": [{"line_id": "atta", "product_key": "aashirvaad_atta", "qty": 1}],
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
    # needs oil (fortune_oil), surf (surf_liquid), almonds (california_almonds), ghee (amul_ghee).
    # Offer A1 amazon flat 5000 >= 50000, uses 2.
    # Assert: 200. Every need is in exactly one order of cheapest_now.
    # cheapest_now.total_net_paise <= baseline.total_net_paise.
    # Reasons are a list of objects with non-empty text.
    resp = client.post(
        "/api/v1/plans",
        json={
            "needs": [
                {"line_id": "oil", "product_key": "fortune_oil", "qty": 1},
                {"line_id": "surf", "product_key": "surf_liquid", "qty": 1},
                {"line_id": "almonds", "product_key": "california_almonds", "qty": 1},
                {"line_id": "ghee", "product_key": "amul_ghee", "qty": 1},
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
    assert sorted(found_lines) == sorted(all_need_ids)

    # Reasons are non-empty
    for r in cn["reasons"]:
        assert r["text"] != ""
        assert "code" in r
        assert "platform" in r
        assert "amount_paise" in r
        assert "line_ids" in r


def test_6_pending_through_api() -> None:
    # 6. Pending through the API: needs surf (surf_liquid) only, lock_platform: "amazon".
    # A1 uses 2. Fillers: one amazon listing from the seed whose price closes the gap.
    # Assert that if max_savings is present, it has exactly one order with status: "pending",
    # a positive shortfall_paise, and target_offer_id == "A1", and that its filler lines have is_filler: true.
    seed = load_seed()
    surf_amazon = next(
        item for item in seed if item.product_key == "surf_liquid" and item.platform == "amazon"
    )
    surf_price = unit_price(surf_amazon.item_price(), is_member=True)
    shortfall = 50000 - surf_price

    # Find an amazon filler listing that can close the shortfall
    filler_listing = next(
        item
        for item in seed
        if item.platform == "amazon"
        and item.product_key != "surf_liquid"
        and unit_price(item.item_price(), is_member=True) >= shortfall
        and unit_price(item.item_price(), is_member=True) <= 25000
    )

    resp = client.post(
        "/api/v1/plans",
        json={
            "needs": [
                {
                    "line_id": "surf",
                    "product_key": "surf_liquid",
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
                {"line_id": "oil", "product_key": "fortune_oil", "qty": 1},
                {"line_id": "surf", "product_key": "surf_liquid", "qty": 1},
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
            "needs": [{"line_id": "atta", "product_key": "aashirvaad_atta", "qty": 1}],
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
            "needs": [{"line_id": "atta", "product_key": "aashirvaad_atta", "qty": 1}],
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
            "needs": [{"line_id": "atta", "product_key": "aashirvaad_atta", "qty": 1}],
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
        json={"needs": [{"line_id": "atta", "product_key": "aashirvaad_atta", "qty": 1}]},
    )
    assert r2.status_code == 422
    assert "simulated optimizer failure" in r2.json()["detail"]


def test_11_duplicate_and_conflicting_filler_id() -> None:
    # Duplicate filler_id -> 422
    r1 = client.post(
        "/api/v1/plans",
        json={
            "needs": [{"line_id": "atta", "product_key": "aashirvaad_atta", "qty": 1}],
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
            "needs": [{"line_id": "atta", "product_key": "aashirvaad_atta", "qty": 1}],
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
        json={"needs": [{"line_id": "atta", "product_key": "aashirvaad_atta", "qty": 0}]},
    )
    assert r_zero.status_code == 422

    r_negative = client.post(
        "/api/v1/plans",
        json={"needs": [{"line_id": "atta", "product_key": "aashirvaad_atta", "qty": -1}]},
    )
    assert r_negative.status_code == 422

    r_100 = client.post(
        "/api/v1/plans",
        json={"needs": [{"line_id": "atta", "product_key": "aashirvaad_atta", "qty": 100}]},
    )
    assert r_100.status_code == 422

    r_1 = client.post(
        "/api/v1/plans",
        json={"needs": [{"line_id": "atta", "product_key": "aashirvaad_atta", "qty": 1}]},
    )
    assert r_1.status_code == 200

    r_99 = client.post(
        "/api/v1/plans",
        json={"needs": [{"line_id": "atta", "product_key": "aashirvaad_atta", "qty": 99}]},
    )
    assert r_99.status_code == 200
