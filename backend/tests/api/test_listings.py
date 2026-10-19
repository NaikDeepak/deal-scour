from collections.abc import Generator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from app.api.v1.baskets import router as baskets_router
from app.api.v1.deals import router as deals_router
from app.api.v1.listings import router as listings_router
from app.api.v1.lists import router as lists_router
from app.api.v1.offers import router as offers_router
from app.api.v1.plans import router as plans_router
from app.api.v1.prices import router as prices_router
from app.core.db import get_session
from app.core.security import hash_token
from app.domain.models import (
    AppUser,
    AuthSession,
    CustomListing,
    Household,
    HouseholdMember,
    PriceObservation,
)


@pytest.fixture
def listings_client(engine: Engine) -> Generator[TestClient, None, None]:
    app = FastAPI()
    app.include_router(listings_router, prefix="/api/v1")
    app.include_router(lists_router, prefix="/api/v1")
    app.include_router(offers_router, prefix="/api/v1")
    app.include_router(baskets_router, prefix="/api/v1")
    app.include_router(plans_router, prefix="/api/v1")
    app.include_router(deals_router, prefix="/api/v1")
    app.include_router(prices_router, prefix="/api/v1")

    def override_get_session() -> Generator[Session, None, None]:
        with Session(engine) as s:
            yield s

    app.dependency_overrides[get_session] = override_get_session

    with Session(engine) as s:
        user = s.exec(select(AppUser).where(AppUser.email == "owner@dealscour.local")).first()
        if not user:
            user = AppUser(
                email="owner@dealscour.local",
                name="Test Owner",
                created_at=datetime.now(UTC),
            )
            s.add(user)
            s.commit()
            s.refresh(user)

        assert user.id is not None
        mem = s.exec(
            select(HouseholdMember).where(
                HouseholdMember.household_id == 1,
                HouseholdMember.user_id == user.id,
            )
        ).first()
        if not mem:
            mem = HouseholdMember(household_id=1, user_id=user.id, role="owner")
            s.add(mem)
            s.commit()

        token = "test-persistent-session-token-for-tests-32ch"
        token_h = hash_token(token)
        auth_sess = s.exec(select(AuthSession).where(AuthSession.token_hash == token_h)).first()
        if not auth_sess:
            auth_sess = AuthSession(
                token_hash=token_h,
                user_id=user.id,
                created_at=datetime.now(UTC),
                expires_at=datetime.now(UTC) + timedelta(days=365),
                last_seen_at=datetime.now(UTC),
            )
            s.add(auth_sess)
            s.commit()

    with TestClient(app) as c:
        c.cookies.set("ds_session", token)
        c.headers["X-DealScour"] = "1"
        yield c


def test_case_2_post_listings_and_catalog_integration(listings_client: TestClient) -> None:
    # 1. POST /listings/parse
    parse_res = listings_client.post(
        "/api/v1/listings/parse",
        json={"url": "https://www.amazon.in/Amul-Butter-500g/dp/B00ZXUW9ZK/ref=sr_1_1?keywords=amul+butter"},
    )
    assert parse_res.status_code == 200, parse_res.text
    assert parse_res.json() == {
        "platform": "amazon",
        "sku": "B00ZXUW9ZK",
        "url": "https://www.amazon.in/dp/B00ZXUW9ZK",
    }

    # 2. POST /listings creates cus-1 with slug product_key and observation
    post_res = listings_client.post(
        "/api/v1/listings",
        json={
            "url": "https://www.amazon.in/Amul-Butter-500g/dp/B00ZXUW9ZK/ref=sr_1_1?keywords=amul+butter",
            "title": "Amul Butter",
            "brand": "Amul",
            "pack_label": "500g",
            "category": "dairy",
            "family_key": "butter",
            "listed_paise": 27500,
            "mrp_paise": 28500,
            "member_price_paise": 26000,
            "in_stock": True,
        },
    )
    assert post_res.status_code == 201, post_res.text
    data = post_res.json()
    assert data["listing_id"] == "cus-1"
    assert data["product_key"] == "amul_butter_500g"
    assert data["platform"] == "amazon"
    assert data["sku"] == "B00ZXUW9ZK"
    assert data["url"] == "https://www.amazon.in/dp/B00ZXUW9ZK"
    assert data["family_key"] == "butter"

    # GET /deals includes it with price_source "manual"
    deals_res = listings_client.get("/api/v1/deals")
    assert deals_res.status_code == 200
    deals = deals_res.json()["deals"]
    custom_deal = next((d for d in deals if d["id"] == "cus-1"), None)
    assert custom_deal is not None
    assert custom_deal["price_source"] == "manual"
    assert custom_deal["listed_paise"] == 27500
    assert custom_deal["mrp_paise"] == 28500
    assert custom_deal["unit_price_paise"] == 26000  # amazon member

    # An exact need on its product_key plans to it
    plan_res = listings_client.post(
        "/api/v1/plans",
        json={
            "needs": [{"line_id": "line-1", "product_key": data["product_key"], "qty": 1}],
        },
    )
    assert plan_res.status_code == 200, plan_res.text
    cheapest_plan = next(p for p in plan_res.json()["plans"] if p["label"] == "cheapest_now")
    assert len(cheapest_plan["orders"]) == 1
    assert cheapest_plan["orders"][0]["platform"] == "amazon"
    assert cheapest_plan["orders"][0]["lines"][0]["listing_id"] == "cus-1"

    # A family need on its family_key (with quantity in its unit) considers it
    fam_plan_res = listings_client.post(
        "/api/v1/plans",
        json={
            "needs": [{"line_id": "line-fam", "family_key": "butter", "quantity": "500g", "qty": 1}],
        },
    )
    assert fam_plan_res.status_code == 200, fam_plan_res.text
    fam_cheapest = next(p for p in fam_plan_res.json()["plans"] if p["label"] == "cheapest_now")
    assert len(fam_cheapest["orders"]) == 1
    assert fam_cheapest["orders"][0]["lines"][0]["listing_id"] == "cus-1"


def test_case_3_duplicate_and_archive(listings_client: TestClient) -> None:
    # Initial POST
    res = listings_client.post(
        "/api/v1/listings",
        json={
            "url": "https://www.amazon.in/dp/B00ZXUW9ZK",
            "title": "Amul Butter",
            "brand": "Amul",
            "pack_label": "500g",
            "category": "dairy",
            "family_key": "butter",
            "listed_paise": 27500,
            "mrp_paise": 28500,
        },
    )
    assert res.status_code == 201

    # Duplicate (platform, sku) -> 409
    res_dup = listings_client.post(
        "/api/v1/listings",
        json={
            "url": "https://www.amazon.in/Amul-Butter/dp/B00ZXUW9ZK",
            "title": "Amul Butter 500g Pack",
            "brand": "Amul",
            "pack_label": "500g",
            "category": "dairy",
            "family_key": "butter",
            "listed_paise": 27500,
            "mrp_paise": 28500,
        },
    )
    assert res_dup.status_code == 409

    # Archive cus-1
    res_patch = listings_client.patch(
        "/api/v1/listings/cus-1",
        json={"archived": True},
    )
    assert res_patch.status_code == 200
    assert res_patch.json()["archived"] is True

    # Same sku after archiving -> allowed
    res_after = listings_client.post(
        "/api/v1/listings",
        json={
            "url": "https://www.amazon.in/dp/B00ZXUW9ZK",
            "title": "Amul Butter New",
            "brand": "Amul",
            "pack_label": "500g",
            "category": "dairy",
            "family_key": "butter",
            "listed_paise": 27500,
            "mrp_paise": 28500,
        },
    )
    assert res_after.status_code == 201
    assert res_after.json()["listing_id"] == "cus-2"


def test_case_4_validation(listings_client: TestClient) -> None:
    valid_payload = {
        "url": "https://www.amazon.in/dp/B00ZXUW9ZK",
        "title": "Amul Butter",
        "brand": "Amul",
        "pack_label": "500g",
        "category": "dairy",
        "family_key": "butter",
        "listed_paise": 27500,
        "mrp_paise": 28500,
    }

    # Bad pack_label
    p1 = dict(valid_payload, pack_label="lots")
    assert listings_client.post("/api/v1/listings", json=p1).status_code == 422

    # Unknown platform URL
    p2 = dict(valid_payload, url="https://www.bigbasket.com/pd/1/")
    assert listings_client.post("/api/v1/listings", json=p2).status_code == 422

    # Title too long (> 120 chars)
    p3 = dict(valid_payload, title="A" * 121)
    assert listings_client.post("/api/v1/listings", json=p3).status_code == 422

    # mrp < listed
    p4 = dict(valid_payload, mrp_paise=20000, listed_paise=25000)
    assert listings_client.post("/api/v1/listings", json=p4).status_code == 422

    # member > listed
    p5 = dict(valid_payload, member_price_paise=30000, listed_paise=25000)
    assert listings_client.post("/api/v1/listings", json=p5).status_code == 422

    # Short links -> 422
    p6 = dict(valid_payload, url="https://amzn.in/d/abcd123")
    assert listings_client.post("/api/v1/listings", json=p6).status_code == 422


def test_case_5_product_key_clash(listings_client: TestClient) -> None:
    # First product with brand "Pintola", title "Peanut Butter", pack "1kg"
    res1 = listings_client.post(
        "/api/v1/listings",
        json={
            "url": "https://www.amazon.in/dp/B00PINT001",
            "title": "Peanut Butter",
            "brand": "Pintola",
            "pack_label": "1kg",
            "category": "staples",
            "family_key": "peanut_butter",
            "listed_paise": 40000,
            "mrp_paise": 50000,
        },
    )
    assert res1.status_code == 201
    pk1 = res1.json()["product_key"]
    assert pk1 == "pintola_peanut_butter_1kg"

    # Second product with different sku (on Blinkit) but same brand/title/pack
    res2 = listings_client.post(
        "/api/v1/listings",
        json={
            "url": "https://blinkit.com/prn/pintola-peanut-butter/prid/998877",
            "title": "Peanut Butter",
            "brand": "Pintola",
            "pack_label": "1kg",
            "category": "staples",
            "family_key": "peanut_butter",
            "listed_paise": 42000,
            "mrp_paise": 50000,
        },
    )
    assert res2.status_code == 201
    pk2 = res2.json()["product_key"]
    assert pk2 == "pintola_peanut_butter_1kg_2"


def test_case_6_household_isolation(listings_client: TestClient, engine: Engine) -> None:
    # Insert custom listing directly for household 2
    with Session(engine) as s:
        # Create household 2
        hh2 = s.get(Household, 2)
        if not hh2:
            hh2 = Household(id=2, name="Other Home", pincode="411018")
            s.add(hh2)
            s.commit()

        custom_hh2 = CustomListing(
            household_id=2,
            listing_id="cus-hh2",
            platform="amazon",
            sku="B00HH2ISOL",
            url="https://www.amazon.in/dp/B00HH2ISOL",
            title="Secret Butter",
            brand="Secret",
            pack_label="500g",
            category="dairy",
            product_key="secret_butter_500g",
            family_key="secret_family",
            archived=False,
            created_at=datetime.now(UTC),
        )
        s.add(custom_hh2)
        s.commit()
        obs = PriceObservation(
            household_id=2,
            listing_id="cus-hh2",
            listed_paise=10000,
            mrp_paise=15000,
            source="manual",
            observed_at=datetime.now(UTC),
        )
        s.add(obs)
        s.commit()

    # Household 1 checks:
    # 1. GET /deals does not include cus-hh2
    deals = listings_client.get("/api/v1/deals").json()["deals"]
    assert not any(d["id"] == "cus-hh2" for d in deals)

    # 2. GET /listings does not include cus-hh2
    listings = listings_client.get("/api/v1/listings").json()
    assert not any(item["listing_id"] == "cus-hh2" for item in listings)

    # 3. GET /catalog/families does not include secret_family
    fams = listings_client.get("/api/v1/catalog/families").json()
    assert not any(f["family_key"] == "secret_family" for f in fams)

    # 4. PATCH /listings/cus-hh2 returns 404 for household 1
    assert listings_client.patch("/api/v1/listings/cus-hh2", json={"title": "Hacked"}).status_code == 404

    # 5. cus-hh2 as a filler in plans -> 422 for household 1
    res_plan = listings_client.post(
        "/api/v1/plans",
        json={
            "needs": [{"line_id": "n1", "product_key": "fortune_sunlite_oil_5l", "qty": 1}],
            "fillers": [{"filler_id": "f1", "listing_id": "cus-hh2", "score": 10}],
        },
    )
    assert res_plan.status_code == 422


def test_case_7_patch_archive_and_unpriced_list_need(listings_client: TestClient) -> None:
    # Create custom listing
    post_res = listings_client.post(
        "/api/v1/listings",
        json={
            "url": "https://www.amazon.in/dp/B00AMZTES1",
            "title": "Organic Honey",
            "brand": "Dabur",
            "pack_label": "500g",
            "category": "staples",
            "family_key": "honey",
            "listed_paise": 20000,
            "mrp_paise": 25000,
        },
    )
    assert post_res.status_code == 201
    listing = post_res.json()
    pk = listing["product_key"]
    lid = listing["listing_id"]

    # Create a shopping list with a need for this custom listing
    list_res = listings_client.post("/api/v1/lists", json={"name": "Honey List", "kind": "quick"})
    assert list_res.status_code == 201
    list_id = list_res.json()["id"]

    need_res = listings_client.post(
        f"/api/v1/lists/{list_id}/needs",
        json={"line_id": "honey_need", "product_key": pk, "qty": 1},
    )
    assert need_res.status_code == 201

    # Plan the list: should plan to this listing
    plan1 = listings_client.post(f"/api/v1/lists/{list_id}/plan", json={}).json()
    cheapest1 = next(p for p in plan1["plans"] if p["label"] == "cheapest_now")
    assert len(cheapest1["unpriced"]) == 0
    assert cheapest1["orders"][0]["lines"][0]["listing_id"] == lid

    # Archive the custom listing
    patch_res = listings_client.patch(f"/api/v1/listings/{lid}", json={"archived": True})
    assert patch_res.status_code == 200
    assert patch_res.json()["archived"] is True

    # Deals: disappears from deals
    deals = listings_client.get("/api/v1/deals").json()["deals"]
    assert not any(d["id"] == lid for d in deals)

    # Planning the saved list now fails because its only need has no listing left
    plan2_res = listings_client.post(f"/api/v1/lists/{list_id}/plan", json={})
    assert plan2_res.status_code == 422
    assert f"No prices yet for: {pk.replace('_', ' ')}" in plan2_res.text


def test_case_8_catalog_families(listings_client: TestClient) -> None:
    # Before adding custom listing, check seed families
    res1 = listings_client.get("/api/v1/catalog/families")
    assert res1.status_code == 200
    families1 = res1.json()
    keys1 = [f["family_key"] for f in families1]
    assert "sunflower_oil" in keys1
    assert "atta" in keys1
    # Check sorted
    assert keys1 == sorted(keys1)

    # Add custom listing with new family 'cheese_slices'
    post_res = listings_client.post(
        "/api/v1/listings",
        json={
            "url": "https://www.amazon.in/dp/B00CHEESE1",
            "title": "Cheese Slices",
            "brand": "Amul",
            "pack_label": "200g",
            "category": "dairy",
            "family_key": "cheese_slices",
            "listed_paise": 15000,
            "mrp_paise": 16000,
        },
    )
    assert post_res.status_code == 201

    # GET /catalog/families should now include cheese_slices
    res2 = listings_client.get("/api/v1/catalog/families")
    assert res2.status_code == 200
    families2 = res2.json()
    cheese_fam = next((f for f in families2 if f["family_key"] == "cheese_slices"), None)
    assert cheese_fam is not None
    assert cheese_fam["count"] == 1
    assert "g" in cheese_fam["units"]
    keys2 = [f["family_key"] for f in families2]
    assert keys2 == sorted(keys2)


def test_review_item_13_archived_custom_listing_excluded_from_need_validation(
    listings_client: TestClient,
) -> None:
    # Create and archive a custom listing
    res = listings_client.post(
        "/api/v1/listings",
        json={
            "url": "https://www.amazon.in/dp/B00EXCLU13",
            "title": "Exclusive Ghee",
            "brand": "Govind",
            "pack_label": "1l",
            "category": "dairy",
            "family_key": "ghee",
            "listed_paise": 65000,
            "mrp_paise": 70000,
        },
    )
    assert res.status_code == 201
    pk = res.json()["product_key"]
    lid = res.json()["listing_id"]

    # Archive it
    arch_res = listings_client.patch(f"/api/v1/listings/{lid}", json={"archived": True})
    assert arch_res.status_code == 200

    # Submitting need via POST /plans on archived product_key -> 422
    plan_res = listings_client.post(
        "/api/v1/plans",
        json={"needs": [{"line_id": "item13_need", "product_key": pk, "qty": 1}]},
    )
    assert plan_res.status_code == 422
    assert f"Unknown product_key: {pk}" in plan_res.text

    # Submitting need via POST /lists/{id}/needs on archived product_key -> 422
    list_res = listings_client.post("/api/v1/lists", json={"name": "Temp List", "kind": "quick"})
    assert list_res.status_code == 201
    list_id = list_res.json()["id"]

    need_res = listings_client.post(
        f"/api/v1/lists/{list_id}/needs",
        json={"line_id": "temp_need", "product_key": pk, "qty": 1},
    )
    assert need_res.status_code == 422
    assert f"Unknown product_key: {pk}" in need_res.text


def test_review_item_14_unique_product_key_and_integrity_error_retry(
    listings_client: TestClient,
) -> None:
    # 1. Create first listing with base slug
    res1 = listings_client.post(
        "/api/v1/listings",
        json={
            "url": "https://www.amazon.in/dp/B00SALT001",
            "title": "Pure Salt",
            "brand": "Tata",
            "pack_label": "1kg",
            "category": "staples",
            "family_key": "salt",
            "listed_paise": 2800,
            "mrp_paise": 3000,
        },
    )
    assert res1.status_code == 201
    assert res1.json()["product_key"] == "tata_pure_salt_1kg"
    lid1 = res1.json()["listing_id"]

    # Archive listing 1 so it is excluded from all_listings (simulating collision on unlisted key)
    listings_client.patch(f"/api/v1/listings/{lid1}", json={"archived": True})

    # 2. Create second listing with same brand/title/pack (different sku)
    # create_listing will try base slug "tata_pure_salt_1kg", hit IntegrityError,
    # retry with next suffix "_2" and succeed.
    res2 = listings_client.post(
        "/api/v1/listings",
        json={
            "url": "https://blinkit.com/prn/tata-pure-salt/prid/123456",
            "title": "Pure Salt",
            "brand": "Tata",
            "pack_label": "1kg",
            "category": "staples",
            "family_key": "salt",
            "listed_paise": 2900,
            "mrp_paise": 3000,
        },
    )
    assert res2.status_code == 201
    assert res2.json()["product_key"] == "tata_pure_salt_1kg_2"
    lid2 = res2.json()["listing_id"]

    # Archive listing 2 as well so both base and "_2" are in DB
    listings_client.patch(f"/api/v1/listings/{lid2}", json={"archived": True})

    # 3. Create third listing with same brand/title/pack (different sku)
    # create_listing tries base slug -> IntegrityError, tries "_2" -> IntegrityError,
    # and raises 409 Conflict.
    res3 = listings_client.post(
        "/api/v1/listings",
        json={
            "url": "https://www.flipkart.com/tata-pure-salt/p/itm123456789?pid=TATSALT001",
            "title": "Pure Salt",
            "brand": "Tata",
            "pack_label": "1kg",
            "category": "staples",
            "family_key": "salt",
            "listed_paise": 2900,
            "mrp_paise": 3000,
        },
    )
    assert res3.status_code == 409
    assert "Product key collision could not be resolved" in res3.text

