from collections.abc import Generator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from app.api.v1.listings import router as listings_router
from app.api.v1.watch import router as watch_router
from app.core import clock
from app.core.db import get_session
from app.core.security import hash_token
from app.domain.models import (
    AppUser,
    AuthSession,
    CustomListing,
    Household,
    HouseholdMember,
    ListingWatch,
    PriceObservation,
)

FIXED_NOW = datetime(2026, 10, 19, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def watch_client(engine: Engine) -> Generator[TestClient, None, None]:
    app = FastAPI()
    app.include_router(listings_router, prefix="/api/v1")
    app.include_router(watch_router, prefix="/api/v1")

    def override_get_session() -> Generator[Session, None, None]:
        with Session(engine) as s:
            yield s

    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[clock.now] = lambda: FIXED_NOW

    with Session(engine) as s:
        # Seed user and household 1
        user1 = s.exec(select(AppUser).where(AppUser.email == "owner@dealscour.local")).first()
        if not user1:
            user1 = AppUser(
                email="owner@dealscour.local",
                name="Test Owner",
                created_at=FIXED_NOW,
            )
            s.add(user1)
            s.commit()
            s.refresh(user1)

        mem1 = s.exec(
            select(HouseholdMember).where(
                HouseholdMember.household_id == 1,
                HouseholdMember.user_id == user1.id,
            )
        ).first()
        if not mem1:
            mem1 = HouseholdMember(household_id=1, user_id=user1.id, role="owner")
            s.add(mem1)
            s.commit()

        token = "test-persistent-session-token-for-tests-32ch"
        token_h = hash_token(token)
        auth_sess = s.exec(select(AuthSession).where(AuthSession.token_hash == token_h)).first()
        if not auth_sess:
            auth_sess = AuthSession(
                token_hash=token_h,
                user_id=user1.id,
                created_at=FIXED_NOW,
                expires_at=FIXED_NOW + timedelta(days=365),
                last_seen_at=FIXED_NOW,
            )
            s.add(auth_sess)
            s.commit()

    c = TestClient(app)
    c.cookies.set("ds_session", "test-persistent-session-token-for-tests-32ch")
    c.headers["X-DealScour"] = "1"
    yield c


# 6. Bulk: 3 urls → 3 suggestions, nothing saved; > 20 → 422.
def test_bulk_autofill_limits_and_no_save(watch_client: TestClient, engine: Engine) -> None:
    urls_3 = [
        "https://blinkit.com/prn/amul-salted-butter/prid/10001",
        "https://blinkit.com/prn/britannia-brown-bread/prid/10002",
        "https://blinkit.com/prn/mother-dairy-paneer/prid/10003",
    ]

    with Session(engine) as s:
        initial_count = len(s.exec(select(CustomListing)).all())

    resp = watch_client.post("/api/v1/listings/bulk", json={"urls": urls_3})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["results"]) == 3
    assert data["results"][0]["suggestion"]["brand"] == "Amul"
    assert data["results"][1]["suggestion"]["brand"] == "Britannia"
    assert data["results"][2]["suggestion"]["brand"] == "Mother Dairy"

    # Verify nothing was saved to DB
    with Session(engine) as s:
        assert len(s.exec(select(CustomListing)).all()) == initial_count

    # > 20 URLs -> 422
    urls_21 = [f"https://blinkit.com/prn/item-{i}/prid/{10000+i}" for i in range(21)]
    resp_21 = watch_client.post("/api/v1/listings/bulk", json={"urls": urls_21})
    assert resp_21.status_code == 422


# 7. History stats: low/avg/high over 30 days with fixed clock.
def test_history_stats_calculation(watch_client: TestClient, engine: Engine) -> None:
    listing_id = "test_hist_listing_1"
    with Session(engine) as s:
        cl = CustomListing(
            household_id=1,
            listing_id=listing_id,
            platform="amazon",
            sku="B0TEST1234",
            url="https://www.amazon.in/dp/B0TEST1234",
            title="Test Butter 500g",
            brand="Amul",
            pack_label="500g",
            category="dairy",
            product_key="butter_500g",
            family_key="butter",
            created_at=FIXED_NOW - timedelta(days=60),
        )
        s.add(cl)

        # 4 observations: 10d ago (25000), 20d ago (20000), 25d ago (30000), 45d ago (15000)
        obs = [
            PriceObservation(
                household_id=1,
                listing_id=listing_id,
                listed_paise=25000,
                mrp_paise=30000,
                in_stock=True,
                source="fetcher",
                observed_at=FIXED_NOW - timedelta(days=10),
            ),
            PriceObservation(
                household_id=1,
                listing_id=listing_id,
                listed_paise=20000,
                mrp_paise=30000,
                in_stock=True,
                source="fetcher",
                observed_at=FIXED_NOW - timedelta(days=20),
            ),
            PriceObservation(
                household_id=1,
                listing_id=listing_id,
                listed_paise=30000,
                mrp_paise=30000,
                in_stock=True,
                source="fetcher",
                observed_at=FIXED_NOW - timedelta(days=25),
            ),
            PriceObservation(
                household_id=1,
                listing_id=listing_id,
                listed_paise=15000,
                mrp_paise=30000,
                in_stock=True,
                source="fetcher",
                observed_at=FIXED_NOW - timedelta(days=45),
            ),
        ]
        s.add_all(obs)
        s.commit()

    resp = watch_client.get(f"/api/v1/listings/{listing_id}/history?days=90")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["observations"]) == 4
    # 30-day stats should only consider the 3 observations within 30 days (25000, 20000, 30000)
    assert data["low_30d"] == 20000
    assert data["high_30d"] == 30000
    assert data["avg_30d"] == 25000  # (25000 + 20000 + 30000) / 3


def test_watch_endpoints(watch_client: TestClient, engine: Engine) -> None:
    listing_id = "test_watch_listing"
    with Session(engine) as s:
        cl = CustomListing(
            household_id=1,
            listing_id=listing_id,
            platform="amazon",
            sku="B0WATCH123",
            url="https://www.amazon.in/dp/B0WATCH123",
            title="Test Watch Product",
            brand="Amul",
            pack_label="500g",
            category="dairy",
            product_key="watch_prod_1",
            family_key="butter",
            created_at=FIXED_NOW,
        )
        s.add(cl)
        s.commit()

    # PUT watch target
    put_res = watch_client.put(f"/api/v1/listings/{listing_id}/watch", json={"target_paise": 24000})
    assert put_res.status_code == 200
    assert put_res.json()["target_paise"] == 24000

    # Verify in DB
    with Session(engine) as s:
        w = s.exec(select(ListingWatch).where(ListingWatch.listing_id == listing_id)).first()
        assert w is not None
        assert w.target_paise == 24000

    # DELETE watch
    del_res = watch_client.delete(f"/api/v1/listings/{listing_id}/watch")
    assert del_res.status_code == 200

    with Session(engine) as s:
        w = s.exec(select(ListingWatch).where(ListingWatch.listing_id == listing_id)).first()
        assert w is None


# 8. Feed: below target, 30-day low, 15% under average each produce the right reason;
# stale or out-of-stock never appear; another household's never appear.
def test_deals_feed_reasons_and_isolation(watch_client: TestClient, engine: Engine) -> None:
    with Session(engine) as s:
        # Seed household 2
        h2 = Household(id=2, name="Other Household", pincode="560001")
        s.add(h2)
        s.commit()

        # 1. Listing A: below_target (target=25000, current=22000)
        la = CustomListing(
            household_id=1,
            listing_id="listing_a",
            platform="amazon",
            sku="B00000000A",
            url="https://www.amazon.in/dp/B00000000A",
            title="Amul Butter 500g",
            brand="Amul",
            pack_label="500g",
            category="dairy",
            product_key="butter_a",
            family_key="butter",
            created_at=FIXED_NOW,
        )
        s.add(la)
        s.add(ListingWatch(household_id=1, listing_id="listing_a", target_paise=25000, created_at=FIXED_NOW))
        s.add(PriceObservation(
            household_id=1,
            listing_id="listing_a",
            listed_paise=22000,
            mrp_paise=28000,
            in_stock=True,
            source="fetcher",
            observed_at=FIXED_NOW - timedelta(hours=2),
        ))

        # 2. Listing B: low_30d (>= 3 observations, current is lowest)
        lb = CustomListing(
            household_id=1,
            listing_id="listing_b",
            platform="amazon",
            sku="B00000000B",
            url="https://www.amazon.in/dp/B00000000B",
            title="Britannia Bread 400g",
            brand="Britannia",
            pack_label="400g",
            category="bakery",
            product_key="bread_b",
            family_key="bread",
            created_at=FIXED_NOW,
        )
        s.add(lb)
        for i, price in enumerate([5000, 4800, 4500]):
            s.add(PriceObservation(
                household_id=1,
                listing_id="listing_b",
                listed_paise=price,
                mrp_paise=5500,
                in_stock=True,
                source="fetcher",
                observed_at=FIXED_NOW - timedelta(days=3 - i),
            ))

        # 3. Listing C: under_avg (avg=10000, current=8000 -> 20% under avg >= 15%)
        lc = CustomListing(
            household_id=1,
            listing_id="listing_c",
            platform="amazon",
            sku="B00000000C",
            url="https://www.amazon.in/dp/B00000000C",
            title="Tata Salt 1kg",
            brand="Tata",
            pack_label="1kg",
            category="staples",
            product_key="salt_c",
            family_key="salt",
            created_at=FIXED_NOW,
        )
        s.add(lc)
        s.add(PriceObservation(
            household_id=1,
            listing_id="listing_c",
            listed_paise=12000,
            mrp_paise=15000,
            in_stock=True,
            source="fetcher",
            observed_at=FIXED_NOW - timedelta(days=5),
        ))
        s.add(PriceObservation(
            household_id=1,
            listing_id="listing_c",
            listed_paise=8000,
            mrp_paise=15000,
            in_stock=True,
            source="fetcher",
            observed_at=FIXED_NOW - timedelta(hours=1),
        ))

        # 4. Listing D: out of stock (should NOT appear)
        ld = CustomListing(
            household_id=1,
            listing_id="listing_d",
            platform="amazon",
            sku="B00000000D",
            url="https://www.amazon.in/dp/B00000000D",
            title="Out Of Stock Item",
            brand="Amul",
            pack_label="500g",
            category="dairy",
            product_key="prod_d",
            family_key="butter",
            created_at=FIXED_NOW,
        )
        s.add(ld)
        s.add(ListingWatch(household_id=1, listing_id="listing_d", target_paise=30000, created_at=FIXED_NOW))
        s.add(PriceObservation(
            household_id=1,
            listing_id="listing_d",
            listed_paise=20000,
            mrp_paise=30000,
            in_stock=False,  # Out of stock
            source="fetcher",
            observed_at=FIXED_NOW - timedelta(hours=1),
        ))

        # 5. Listing E: stale (> 48h old, should NOT appear)
        le = CustomListing(
            household_id=1,
            listing_id="listing_e",
            platform="amazon",
            sku="B00000000E",
            url="https://www.amazon.in/dp/B00000000E",
            title="Stale Price Item",
            brand="Amul",
            pack_label="500g",
            category="dairy",
            product_key="prod_e",
            family_key="butter",
            created_at=FIXED_NOW,
        )
        s.add(le)
        s.add(ListingWatch(household_id=1, listing_id="listing_e", target_paise=30000, created_at=FIXED_NOW))
        s.add(PriceObservation(
            household_id=1,
            listing_id="listing_e",
            listed_paise=20000,
            mrp_paise=30000,
            in_stock=True,
            source="fetcher",
            observed_at=FIXED_NOW - timedelta(days=10),  # Stale
        ))

        # 6. Listing F: sample source (should NOT appear)
        lf = CustomListing(
            household_id=1,
            listing_id="listing_f",
            platform="amazon",
            sku="B00000000F",
            url="https://www.amazon.in/dp/B00000000F",
            title="Sample Item",
            brand="Amul",
            pack_label="500g",
            category="dairy",
            product_key="prod_f",
            family_key="butter",
            created_at=FIXED_NOW,
        )
        s.add(lf)
        s.add(PriceObservation(
            household_id=1,
            listing_id="listing_f",
            listed_paise=20000,
            mrp_paise=30000,
            in_stock=True,
            source="sample",  # Sample
            observed_at=FIXED_NOW - timedelta(hours=1),
        ))

        # 7. Household 2 Listing (should NOT appear for Household 1)
        lh2 = CustomListing(
            household_id=2,
            listing_id="listing_h2",
            platform="amazon",
            sku="B0000000H2",
            url="https://www.amazon.in/dp/B0000000H2",
            title="Household 2 Item",
            brand="Amul",
            pack_label="500g",
            category="dairy",
            product_key="prod_h2",
            family_key="butter",
            created_at=FIXED_NOW,
        )
        s.add(lh2)
        s.add(ListingWatch(household_id=2, listing_id="listing_h2", target_paise=30000, created_at=FIXED_NOW))
        s.add(PriceObservation(
            household_id=2,
            listing_id="listing_h2",
            listed_paise=20000,
            mrp_paise=30000,
            in_stock=True,
            source="fetcher",
            observed_at=FIXED_NOW - timedelta(hours=1),
        ))

        s.commit()

    res = watch_client.get("/api/v1/deals/feed")
    assert res.status_code == 200
    feed = res.json()["deals"]

    feed_ids = [d["listing_id"] for d in feed]
    assert "listing_a" in feed_ids
    assert "listing_b" in feed_ids
    assert "listing_c" in feed_ids
    assert "listing_d" not in feed_ids  # out of stock
    assert "listing_e" not in feed_ids  # stale
    assert "listing_f" not in feed_ids  # sample
    assert "listing_h2" not in feed_ids  # other household

    # Verify reasons
    deal_a = next(d for d in feed if d["listing_id"] == "listing_a")
    assert "below_target" in deal_a["reasons"]

    deal_b = next(d for d in feed if d["listing_id"] == "listing_b")
    assert "low_30d" in deal_b["reasons"]

    deal_c = next(d for d in feed if d["listing_id"] == "listing_c")
    assert "under_avg" in deal_c["reasons"]


# 21. Bulk with 1 bad + 2 good urls → 200, 3 results, the bad one has error.
def test_bulk_autofill_per_row_results(watch_client: TestClient) -> None:
    urls = [
        "https://blinkit.com/prn/amul-butter/prid/101",
        "https://invalid-host.example.com/not-a-product",
        "https://blinkit.com/prn/britannia-bread/prid/102",
    ]
    resp = watch_client.post("/api/v1/listings/bulk", json={"urls": urls})
    assert resp.status_code == 200
    results = resp.json()["results"]
    assert len(results) == 3
    assert results[0]["url"] == urls[0]
    assert results[0]["suggestion"] is not None
    assert results[0]["error"] is None

    assert results[1]["url"] == urls[1]
    assert results[1]["suggestion"] is None
    assert results[1]["error"] is not None

    assert results[2]["url"] == urls[2]
    assert results[2]["suggestion"] is not None
    assert results[2]["error"] is None


# 22. Flat price ×3 → no low_30d; 300, 320, 290 (current 290) → low_30d.
def test_low_30d_requires_price_movement(watch_client: TestClient, engine: Engine) -> None:
    with Session(engine) as s:
        cl_flat = CustomListing(
            household_id=1,
            listing_id="listing_flat",
            platform="amazon",
            sku="B00000FLAT",
            url="https://www.amazon.in/dp/B00000FLAT",
            title="Flat Price Product",
            brand="Amul",
            pack_label="500g",
            category="dairy",
            product_key="prod_flat",
            family_key="butter",
            created_at=FIXED_NOW,
        )
        s.add(cl_flat)
        for i in range(3):
            s.add(PriceObservation(
                household_id=1,
                listing_id="listing_flat",
                listed_paise=30000,
                mrp_paise=35000,
                in_stock=True,
                source="fetcher",
                observed_at=FIXED_NOW - timedelta(days=3 - i),
            ))

        cl_moved = CustomListing(
            household_id=1,
            listing_id="listing_moved",
            platform="amazon",
            sku="B0000MOVED",
            url="https://www.amazon.in/dp/B0000MOVED",
            title="Price Moved Product",
            brand="Amul",
            pack_label="500g",
            category="dairy",
            product_key="prod_moved",
            family_key="butter",
            created_at=FIXED_NOW,
        )
        s.add(cl_moved)
        for i, price in enumerate([30000, 32000, 29000]):
            s.add(PriceObservation(
                household_id=1,
                listing_id="listing_moved",
                listed_paise=price,
                mrp_paise=35000,
                in_stock=True,
                source="fetcher",
                observed_at=FIXED_NOW - timedelta(days=3 - i),
            ))
        s.commit()

    res = watch_client.get("/api/v1/deals/feed")
    assert res.status_code == 200
    feed = res.json()["deals"]

    flat_deal = next((d for d in feed if d["listing_id"] == "listing_flat"), None)
    if flat_deal:
        assert "low_30d" not in flat_deal["reasons"]

    moved_deal = next(d for d in feed if d["listing_id"] == "listing_moved")
    assert "low_30d" in moved_deal["reasons"]


# 23. avg of [100, 101] paise = 101 (integer rounding half up); 85.0% exactly under → under_avg.
def test_integer_money_averages_and_under_avg(watch_client: TestClient, engine: Engine) -> None:
    listing_id = "listing_int_avg"
    with Session(engine) as s:
        cl = CustomListing(
            household_id=1,
            listing_id=listing_id,
            platform="amazon",
            sku="B000INTAVG",
            url="https://www.amazon.in/dp/B000INTAVG",
            title="Integer Avg Test",
            brand="Amul",
            pack_label="500g",
            category="dairy",
            product_key="prod_int_avg",
            family_key="butter",
            created_at=FIXED_NOW,
        )
        s.add(cl)
        s.add(PriceObservation(
            household_id=1,
            listing_id=listing_id,
            listed_paise=100,
            mrp_paise=200,
            in_stock=True,
            source="fetcher",
            observed_at=FIXED_NOW - timedelta(days=2),
        ))
        s.add(PriceObservation(
            household_id=1,
            listing_id=listing_id,
            listed_paise=101,
            mrp_paise=200,
            in_stock=True,
            source="fetcher",
            observed_at=FIXED_NOW - timedelta(days=1),
        ))
        s.commit()

    hist = watch_client.get(f"/api/v1/listings/{listing_id}/history").json()
    assert hist["avg_30d"] == 101

    listing_85 = "listing_85_pct"
    with Session(engine) as s:
        cl85 = CustomListing(
            household_id=1,
            listing_id=listing_85,
            platform="amazon",
            sku="B000000085",
            url="https://www.amazon.in/dp/B000000085",
            title="85 Pct Item",
            brand="Amul",
            pack_label="500g",
            category="dairy",
            product_key="prod_85",
            family_key="butter",
            created_at=FIXED_NOW,
        )
        s.add(cl85)
        s.add(PriceObservation(
            household_id=1,
            listing_id=listing_85,
            listed_paise=11000,
            mrp_paise=12000,
            in_stock=True,
            source="fetcher",
            observed_at=FIXED_NOW - timedelta(days=5),
        ))
        s.add(PriceObservation(
            household_id=1,
            listing_id=listing_85,
            listed_paise=10500,
            mrp_paise=12000,
            in_stock=True,
            source="fetcher",
            observed_at=FIXED_NOW - timedelta(days=3),
        ))
        s.add(PriceObservation(
            household_id=1,
            listing_id=listing_85,
            listed_paise=8500,
            mrp_paise=12000,
            in_stock=True,
            source="fetcher",
            observed_at=FIXED_NOW - timedelta(hours=1),
        ))
        s.commit()

    feed_res = watch_client.get("/api/v1/deals/feed").json()["deals"]
    deal_85 = next(d for d in feed_res if d["listing_id"] == listing_85)
    assert "under_avg" in deal_85["reasons"]


# 26. PUT watch on "nope" → 404; on another household's custom listing → 404.
def test_put_watch_only_real_and_owned_listings(watch_client: TestClient, engine: Engine) -> None:
    res_nope = watch_client.put("/api/v1/listings/nope/watch", json={"target_paise": 1000})
    assert res_nope.status_code == 404

    with Session(engine) as s:
        h2 = Household(id=2, name="Other Household", pincode="560001")
        s.add(h2)
        s.commit()

        cl_h2 = CustomListing(
            household_id=2,
            listing_id="h2_secret_listing",
            platform="amazon",
            sku="B0000000H2S",
            url="https://www.amazon.in/dp/B0000000H2S",
            title="Household 2 Secret Item",
            brand="Amul",
            pack_label="500g",
            category="dairy",
            product_key="prod_h2_secret",
            family_key="butter",
            created_at=FIXED_NOW,
        )
        s.add(cl_h2)
        s.commit()

    res_h2 = watch_client.put("/api/v1/listings/h2_secret_listing/watch", json={"target_paise": 1000})
    assert res_h2.status_code == 404


    # An archived custom listing of this household can't be watched either.
    with Session(engine) as s:
        s.add(
            CustomListing(
                household_id=1,
                listing_id="h1_archived_listing",
                platform="amazon",
                sku="B0000000H1A",
                url="https://www.amazon.in/dp/B0000000H1A",
                title="Archived Item",
                brand="Amul",
                pack_label="500g",
                category="dairy",
                product_key="prod_h1_archived",
                family_key="butter",
                archived=True,
                created_at=FIXED_NOW,
            )
        )
        s.commit()

    res_archived = watch_client.put("/api/v1/listings/h1_archived_listing/watch", json={"target_paise": 1000})
    assert res_archived.status_code == 404
