from collections.abc import Generator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlmodel import Session

from app.api.v1.baskets import router as baskets_router
from app.api.v1.deals import router as deals_router
from app.api.v1.lists import router as lists_router
from app.api.v1.offers import router as offers_router
from app.api.v1.plans import router as plans_router
from app.api.v1.prices import router as prices_router
from app.core.db import get_session


@pytest.fixture
def scour_client(engine: Engine) -> Generator[TestClient, None, None]:
    app = FastAPI()
    app.include_router(prices_router, prefix="/api/v1")
    app.include_router(deals_router, prefix="/api/v1")
    app.include_router(plans_router, prefix="/api/v1")
    app.include_router(lists_router, prefix="/api/v1")
    app.include_router(offers_router, prefix="/api/v1")
    app.include_router(baskets_router, prefix="/api/v1")

    def override_get_session() -> Generator[Session, None, None]:
        with Session(engine) as s:
            yield s

    app.dependency_overrides[get_session] = override_get_session
    with TestClient(app) as c:
        yield c


def test_capture_price_by_listing_id_sets_extension_source(scour_client: TestClient) -> None:
    resp = scour_client.post(
        "/api/v1/prices/capture",
        json={
            "listing_id": "stp-4",
            "listed_paise": 61900,
            "mrp_paise": 89000,
            "member_price_paise": 59900,
            "in_stock": True,
            "eta_minutes": 180,
        },
    )
    assert resp.status_code == 201, resp.text
    obs = resp.json()
    assert obs["listing_id"] == "stp-4"
    assert obs["source"] == "extension"
    assert obs["listed_paise"] == 61900
    assert obs["member_price_paise"] == 59900

    deals_resp = scour_client.get("/api/v1/deals")
    assert deals_resp.status_code == 200
    deals_by_id = {d["id"]: d for d in deals_resp.json()["deals"]}
    stp_4 = deals_by_id["stp-4"]
    assert stp_4["price_source"] == "extension"
    assert stp_4["freshness"] == "fresh"
    assert stp_4["unit_price_paise"] == 59900
    assert stp_4["eta_minutes"] == 180

    plans_resp = scour_client.post(
        "/api/v1/plans",
        json={
            "needs": [
                {
                    "line_id": "oil",
                    "product_key": "fortune_sunlite_oil_5l",
                    "qty": 1,
                }
            ],
            "members": ["amazon", "flipkart"],
        },
    )
    assert plans_resp.status_code == 200, plans_resp.text
    amazon_order = next(
        o for o in plans_resp.json()["baseline"]["orders"] if o["platform"] == "amazon"
    )
    oil_line = amazon_order["lines"][0]
    assert oil_line["listing_id"] == "stp-4"
    assert oil_line["unit_price_paise"] == 59900
    assert oil_line["price_source"] == "extension"


def test_capture_price_by_url_resolves_listing(scour_client: TestClient) -> None:
    deals_resp = scour_client.get("/api/v1/deals")
    stp_1 = next(d for d in deals_resp.json()["deals"] if d["id"] == "stp-1")

    resp = scour_client.post(
        "/api/v1/prices/capture",
        json={
            "url": stp_1["url"],
            "listed_paise": 14200,
            "mrp_paise": 19500,
            "in_stock": True,
        },
    )
    assert resp.status_code == 201, resp.text
    obs = resp.json()
    assert obs["listing_id"] == "stp-1"
    assert obs["source"] == "extension"
    assert obs["listed_paise"] == 14200

    bad_resp = scour_client.post(
        "/api/v1/prices/capture",
        json={
            "url": "https://example.com/unknown-product",
            "listed_paise": 14200,
            "mrp_paise": 19500,
        },
    )
    assert bad_resp.status_code == 422


def test_list_scour_targets_returns_candidate_listings_for_open_needs(
    scour_client: TestClient,
) -> None:
    list_resp = scour_client.post(
        "/api/v1/lists",
        json={"name": "Monthly Scour", "kind": "monthly"},
    )
    assert list_resp.status_code == 201
    list_id = list_resp.json()["id"]

    # Add an exact product need (Fortune 5L has Amazon & Flipkart listings: stp-4, stp-5)
    n1 = scour_client.post(
        f"/api/v1/lists/{list_id}/needs",
        json={
            "line_id": "Fortune Oil 5L",
            "product_key": "fortune_sunlite_oil_5l",
            "qty": 1,
        },
    )
    assert n1.status_code == 201

    # Add a family need (atta 5kg has stp-1, stp-2, stp-3)
    n2 = scour_client.post(
        f"/api/v1/lists/{list_id}/needs",
        json={
            "line_id": "Atta 5kg",
            "family_key": "atta",
            "quantity": "5kg",
            "qty": 1,
        },
    )
    assert n2.status_code == 201

    targets_resp = scour_client.get(f"/api/v1/lists/{list_id}/scour-targets")
    assert targets_resp.status_code == 200, targets_resp.text
    data = targets_resp.json()
    target_ids = [t["listing_id"] for t in data["targets"]]
    assert "stp-4" in target_ids
    assert "stp-5" in target_ids
    assert "stp-1" in target_ids
    assert "stp-2" in target_ids
    assert "stp-3" in target_ids
    assert len(target_ids) == len(set(target_ids))

    missing = scour_client.get("/api/v1/lists/99999/scour-targets")
    assert missing.status_code == 404


def test_quick_bundle_dryfruits_500g_and_order_line_url(scour_client: TestClient) -> None:
    list_resp = scour_client.post(
        "/api/v1/lists",
        json={"name": "Dryfruits Run", "kind": "monthly"},
    )
    assert list_resp.status_code == 201
    list_id = list_resp.json()["id"]

    bundle_resp = scour_client.post(
        f"/api/v1/lists/{list_id}/quick-bundle",
        json={"bundle": "dryfruits_500g"},
    )
    assert bundle_resp.status_code == 200, bundle_resp.text
    bdata = bundle_resp.json()
    assert bdata["added_needs"] == 8

    plan_resp = scour_client.post(
        f"/api/v1/lists/{list_id}/plan",
        json={
            "members": ["amazon", "flipkart", "blinkit", "instamart", "zepto"],
            "fillers": [],
        },
    )
    assert plan_resp.status_code == 200, plan_resp.text
    pdata = plan_resp.json()
    cheapest = next(p for p in pdata["plans"] if p["label"] == "cheapest_now")
    assert cheapest["effective_cost_paise"] == 229800
    assert cheapest["savings_vs_baseline_paise"] == 7500
    for order in cheapest["orders"]:
        for line in order["lines"]:
            assert line["url"].startswith("https://")

