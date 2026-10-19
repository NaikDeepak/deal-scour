from collections.abc import Generator
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlmodel import Session, col, func, select

from app.api.v1.baskets import router as baskets_router
from app.api.v1.deals import router as deals_router
from app.api.v1.lists import router as lists_router
from app.api.v1.offers import router as offers_router
from app.api.v1.plans import router as plans_router
from app.api.v1.prices import router as prices_router
from app.core.db import get_session
from app.domain.models import CustomListing, Need, Offer, PriceObservation


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


def _create_real_product_listing(engine: Engine) -> CustomListing:
    with Session(engine) as s:
        cl = CustomListing(
            household_id=1,
            listing_id="amz-ghee-500g",
            platform="amazon",
            sku="B072HG4WNC",
            url="https://www.amazon.in/dp/B072HG4WNC",
            title="Ishavasyam Vedic A2 Ghee 500ml",
            brand="Ishavasyam",
            pack_label="500ml",
            category="staples",
            product_key="ishavasyam_ghee_500ml",
            family_key="cow_ghee",
            icon="🧈",
            created_at=datetime.now(UTC),
        )
        s.add(cl)
        obs = PriceObservation(
            household_id=1,
            listing_id="amz-ghee-500g",
            listed_paise=180000,
            mrp_paise=180000,
            source="manual",
            in_stock=True,
            observed_at=datetime.now(UTC),
        )
        s.add(obs)
        s.commit()
        s.refresh(cl)
        return cl


def test_quick_bundle_adds_needs_only_and_reports_unpriced_families(
    scour_client: TestClient,
    engine: Engine,
) -> None:
    # 1. Quick bundle: adds 8 needs, inserts zero rows in custom_listing, price_observation and offer.
    # Running it twice adds 0. unpriced_families lists bundle families with no listing.
    list_resp = scour_client.post(
        "/api/v1/lists",
        json={"name": "Dryfruits Only Needs", "kind": "monthly"},
    )
    assert list_resp.status_code == 201
    list_id = list_resp.json()["id"]

    with Session(engine) as s:
        cl_before = s.exec(select(func.count(col(CustomListing.id)))).one()
        po_before = s.exec(select(func.count(col(PriceObservation.id)))).one()
        of_before = s.exec(select(func.count(col(Offer.id)))).one()

    # First run
    bundle_resp = scour_client.post(
        f"/api/v1/lists/{list_id}/quick-bundle",
        json={"bundle": "dryfruits_500g"},
    )
    assert bundle_resp.status_code == 200, bundle_resp.text
    bdata = bundle_resp.json()
    assert bdata["added_needs"] == 8
    assert bdata["list_id"] == list_id
    assert bdata["bundle"] == "dryfruits_500g"

    # Seed catalog has almonds, cashews, walnuts.
    # Bundle has cashews, almonds, walnuts, pumpkin_seeds, sunflower_seeds, chia_seeds, flax_seeds, dates.
    # Unpriced families must be exactly the 5 families with no listing in the catalog:
    expected_unpriced = ["pumpkin_seeds", "sunflower_seeds", "chia_seeds", "flax_seeds", "dates"]
    assert bdata["unpriced_families"] == expected_unpriced

    with Session(engine) as s:
        cl_after = s.exec(select(func.count(col(CustomListing.id)))).one()
        po_after = s.exec(select(func.count(col(PriceObservation.id)))).one()
        of_after = s.exec(select(func.count(col(Offer.id)))).one()
        needs_count = s.exec(select(func.count(col(Need.id))).where(Need.list_id == list_id)).one()

    # Assert ZERO rows inserted into custom_listing, price_observation, offer
    assert cl_after == cl_before
    assert po_after == po_before
    assert of_after == of_before
    assert needs_count == 8

    # Second run: running it twice adds 0 needs (existing open needs are not duplicated)
    bundle_resp2 = scour_client.post(
        f"/api/v1/lists/{list_id}/quick-bundle",
        json={"bundle": "dryfruits_500g"},
    )
    assert bundle_resp2.status_code == 200
    assert bundle_resp2.json()["added_needs"] == 0
    assert bundle_resp2.json()["unpriced_families"] == expected_unpriced


def test_capture_tracking_url_and_search_url_rejection(
    scour_client: TestClient,
    engine: Engine,
) -> None:
    # 2. Capture by a tracking-param Amazon url matches the canonical listing.
    # Capture for a listing with a search url -> 422.
    _create_real_product_listing(engine)

    tracking_url = "https://www.amazon.in/dp/B072HG4WNC?tag=dealscour-21&ref_=nav_signin"
    resp = scour_client.post(
        "/api/v1/prices/capture",
        json={
            "url": tracking_url,
            "listed_paise": 175000,
            "mrp_paise": 180000,
            "in_stock": True,
        },
    )
    assert resp.status_code == 201, resp.text
    obs = resp.json()
    assert obs["listing_id"] == "amz-ghee-500g"
    assert obs["listed_paise"] == 175000
    assert obs["source"] == "extension"

    # Attempt capture with a search url -> 422
    search_url_resp = scour_client.post(
        "/api/v1/prices/capture",
        json={
            "url": "https://www.amazon.in/s?k=a2+ghee+500ml",
            "listed_paise": 175000,
        },
    )
    assert search_url_resp.status_code == 422

    # Attempt capture for stp-4 (which has a search url in seed data) -> 422
    listing_with_search_url_resp = scour_client.post(
        "/api/v1/prices/capture",
        json={
            "listing_id": "stp-4",
            "listed_paise": 69500,
        },
    )
    assert listing_with_search_url_resp.status_code == 422


def test_capture_price_jump_requires_confirm(
    scour_client: TestClient,
    engine: Engine,
) -> None:
    # 3. Capture 70% below the latest price -> 422; with confirm: true -> 201. 30% below -> 201.
    _create_real_product_listing(engine)
    # amz-ghee-500g latest price is 180000 paise (₹1,800)

    # 70% below: 180000 * 0.30 = 54000 paise (₹540). Diff = 70% > 60%.
    resp_70_below = scour_client.post(
        "/api/v1/prices/capture",
        json={
            "listing_id": "amz-ghee-500g",
            "listed_paise": 54000,
            "confirm": False,
        },
    )
    assert resp_70_below.status_code == 422
    assert "Price changed a lot. Check the page and confirm." in resp_70_below.json()["detail"]

    # 70% below with confirm: true -> 201
    resp_70_confirmed = scour_client.post(
        "/api/v1/prices/capture",
        json={
            "listing_id": "amz-ghee-500g",
            "listed_paise": 54000,
            "confirm": True,
        },
    )
    assert resp_70_confirmed.status_code == 201
    assert resp_70_confirmed.json()["listed_paise"] == 54000

    # 30% below: 54000 is now latest price. Let's test against 54000 or a new listing.
    # 30% below 54000: 54000 * 0.70 = 37800. Diff = 30% <= 60% -> 201 without confirm
    resp_30_below = scour_client.post(
        "/api/v1/prices/capture",
        json={
            "listing_id": "amz-ghee-500g",
            "listed_paise": 37800,
            "confirm": False,
        },
    )
    assert resp_30_below.status_code == 201
    assert resp_30_below.json()["listed_paise"] == 37800


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
