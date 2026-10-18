from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.deals import router
from app.domain.catalog import load_seed
from app.pricing.landed import unit_price

app = FastAPI()
app.include_router(router, prefix="/api/v1")
client = TestClient(app)


def test_deals_default_members() -> None:
    # Test 5: GET /api/v1/deals -> 200, count == 28, sorted by unit_rate_paise ascending, ties by id
    resp = client.get("/api/v1/deals")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 28
    deals = data["deals"]
    assert len(deals) == 28

    # Verify sort order: unit_rate_paise ascending, ties by id
    rates = [(d["unit_rate_paise"], d["id"]) for d in deals]
    assert rates == sorted(rates)


def test_deals_item_checks() -> None:
    resp = client.get("/api/v1/deals")
    assert resp.status_code == 200
    deals = {d["id"]: d for d in resp.json()["deals"]}

    # Test 6: stp-1 (Instamart, member)
    stp_1 = deals["stp-1"]
    assert stp_1["unit_price_paise"] == 27700
    assert stp_1["unit_rate_paise"] == 5540
    assert stp_1["rate_basis_label"] == "kg"
    assert stp_1["discount_bp"] == 2410
    assert stp_1["delivery_fee_paise"] == 2500
    assert stp_1["free_delivery_min_paise"] == 19900
    assert stp_1["is_member"] is True

    # Test 7: stp-3 (Blinkit, not member)
    stp_3 = deals["stp-3"]
    assert stp_3["unit_price_paise"] == 28900
    assert stp_3["unit_rate_paise"] == 5780
    assert stp_3["delivery_fee_paise"] == 2500
    assert stp_3["free_delivery_min_paise"] == 19900
    assert stp_3["is_member"] is False

    # Test 8: stp-2 (Amazon, Prime)
    stp_2 = deals["stp-2"]
    assert stp_2["unit_price_paise"] == 28300
    assert stp_2["delivery_fee_paise"] == 0
    assert stp_2["free_delivery_min_paise"] == 0


def test_best_in_product() -> None:
    # Test 9: Best per product
    resp = client.get("/api/v1/deals")
    deals = {d["id"]: d for d in resp.json()["deals"]}

    # among aashirvaad_atta, only stp-1 has is_best_in_product
    atta_deals = [d for d in resp.json()["deals"] if d["product_key"] == "aashirvaad_atta"]
    best_atta = [d["id"] for d in atta_deals if d["is_best_in_product"]]
    assert best_atta == ["stp-1"]

    # among california_almonds, alm-1 is best with unit_rate_paise == 6190 and label "100g".
    # alm-2 -> 8000, alm-3 -> 8300.
    alm_1 = deals["alm-1"]
    assert alm_1["is_best_in_product"] is True
    assert alm_1["unit_rate_paise"] == 6190
    assert alm_1["rate_basis_label"] == "100g"

    alm_2 = deals["alm-2"]
    assert alm_2["unit_rate_paise"] == 8000
    assert alm_2["is_best_in_product"] is False

    alm_3 = deals["alm-3"]
    assert alm_3["unit_rate_paise"] == 8300
    assert alm_3["is_best_in_product"] is False

    # wal-1 is best of its own product
    assert deals["wal-1"]["is_best_in_product"] is True


def test_regression_d4_d15_no_delivery_in_unit_price() -> None:
    # Test 10: Regression D4/D15: no field adds delivery to the item.
    # For every deal, unit_price_paise equals pricing.landed.unit_price(...) for that membership state.
    resp = client.get("/api/v1/deals")
    seed_map = {item.id: item for item in load_seed()}
    for deal in resp.json()["deals"]:
        item = seed_map[deal["id"]]
        expected_unit_price = unit_price(item.item_price(), deal["is_member"])
        assert deal["unit_price_paise"] == expected_unit_price


def test_members_param() -> None:
    # Test 11: members=blinkit
    resp = client.get("/api/v1/deals?members=blinkit")
    assert resp.status_code == 200
    deals = {d["id"]: d for d in resp.json()["deals"]}

    stp_3 = deals["stp-3"]
    assert stp_3["unit_price_paise"] == 27700
    assert stp_3["free_delivery_min_paise"] == 0
    assert stp_3["is_best_in_product"] is True

    # stp-1 is now non-member
    stp_1 = deals["stp-1"]
    assert stp_1["unit_price_paise"] == 29200
    assert stp_1["free_delivery_min_paise"] == 49900
    assert stp_1["is_best_in_product"] is False

    # Test 12: members= (empty) -> every is_member is false
    resp_empty = client.get("/api/v1/deals?members=")
    assert resp_empty.status_code == 200
    for d in resp_empty.json()["deals"]:
        assert d["is_member"] is False

    deals_empty = {d["id"]: d for d in resp_empty.json()["deals"]}
    stp_2 = deals_empty["stp-2"]
    assert stp_2["delivery_fee_paise"] == 4000
    assert stp_2["free_delivery_min_paise"] == 49900


def test_validation_errors() -> None:
    # Test 13: unknown platforms or sort
    assert client.get("/api/v1/deals?members=amazon,bigbasket").status_code == 422
    assert client.get("/api/v1/deals?platform=bigbasket").status_code == 422
    assert client.get("/api/v1/deals?sort=cheapest").status_code == 422


def test_filters_and_queries() -> None:
    # Test 14: category=dryfruits -> only dry fruits, and is_best_in_product unchanged
    resp_dry = client.get("/api/v1/deals?category=dryfruits")
    assert resp_dry.status_code == 200
    deals_dry = resp_dry.json()["deals"]
    assert all(d["category"] == "dryfruits" for d in deals_dry)
    alm_1 = next(d for d in deals_dry if d["id"] == "alm-1")
    assert alm_1["is_best_in_product"] is True

    # Test 15: q=AASHIRVAAD -> exactly 3 atta listings. q=zzz -> count == 0, deals == []
    resp_q = client.get("/api/v1/deals?q=AASHIRVAAD")
    assert resp_q.status_code == 200
    deals_q = resp_q.json()["deals"]
    assert len(deals_q) == 3
    assert {d["id"] for d in deals_q} == {"stp-1", "stp-2", "stp-3"}

    resp_empty_q = client.get("/api/v1/deals?q=zzz")
    assert resp_empty_q.status_code == 200
    assert resp_empty_q.json()["count"] == 0
    assert resp_empty_q.json()["deals"] == []


def test_sorting() -> None:
    # Test 16: platform=amazon&sort=price -> only Amazon, unit_price_paise ascending
    resp_amz = client.get("/api/v1/deals?platform=amazon&sort=price")
    assert resp_amz.status_code == 200
    deals_amz = resp_amz.json()["deals"]
    assert all(d["platform"] == "amazon" for d in deals_amz)
    prices = [(d["unit_price_paise"], d["id"]) for d in deals_amz]
    assert prices == sorted(prices)

    # Test 17: sort=discount -> discount_bp descending, ties by id
    resp_disc = client.get("/api/v1/deals?sort=discount")
    assert resp_disc.status_code == 200
    deals_disc = resp_disc.json()["deals"]
    disc_keys = [(-d["discount_bp"], d["id"]) for d in deals_disc]
    assert disc_keys == sorted(disc_keys)

    # sort=eta -> eta_minutes ascending, ties by id
    resp_eta = client.get("/api/v1/deals?sort=eta")
    assert resp_eta.status_code == 200
    deals_eta = resp_eta.json()["deals"]
    eta_keys = [(d["eta_minutes"], d["id"]) for d in deals_eta]
    assert eta_keys == sorted(eta_keys)
