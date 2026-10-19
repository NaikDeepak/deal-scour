from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

import pytest
import sqlalchemy as sa
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from app.api.v1.catalog import router as catalog_router
from app.api.v1.listings import router as listings_router
from app.core.db import get_session
from app.core.security import hash_token, verify_csrf
from app.domain.catalog_import import import_catalog_csv
from app.domain.models import (
    AppUser,
    AuthSession,
    CatalogProduct,
    CustomListing,
    Household,
    HouseholdMember,
)

SAMPLE_CSV = Path(__file__).parent.parent / "fixtures" / "catalog_sample.csv"


@pytest.fixture
def catalog_client(engine: Engine) -> Generator[TestClient, None, None]:
    app = FastAPI()
    csrf = [Depends(verify_csrf)]
    app.include_router(catalog_router, prefix="/api/v1", dependencies=csrf)
    app.include_router(listings_router, prefix="/api/v1", dependencies=csrf)

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

        # Import sample catalog into household 1
        import_catalog_csv(s, household_id=1, csv_path=SAMPLE_CSV)

        # Also create household 2 with its own catalog product
        h2 = s.exec(select(Household).where(Household.id == 2)).first()
        if not h2:
            s.add(Household(id=2, name="Other", pincode="400001"))
            s.commit()
        s.add(
            CatalogProduct(
                household_id=2,
                seed_product_id="OTHER-001",
                name="Tata Sampann Secret Toor Dal",
                brand="Tata Sampann",
                category="Dal & Pulses",
                family_key="toor_dal",
                pack_label="1kg",
                target_pack_weight_g=1000,
            )
        )
        s.commit()

    with TestClient(app) as c:
        c.cookies.set("ds_session", token)
        c.headers["X-DealScour"] = "1"
        yield c


# Case 4: GET /catalog?q=tata toor -> the dal; q=tata rice -> not the dal.
# Another household's catalog -> never returned.
def test_case_4_search_catalog_word_match_and_household_isolation(catalog_client: TestClient) -> None:
    res = catalog_client.get("/api/v1/catalog", params={"q": "tata toor"})
    assert res.status_code == 200, res.text
    items = res.json()
    assert len(items) == 1
    assert items[0]["seed_product_id"] == "DS-0001"
    assert items[0]["name"] == "Tata Sampann Toor/Arhar Dal"
    assert items[0]["family_key"] == "toor_dal"
    assert items[0]["pack_label"] == "600g"

    res_no = catalog_client.get("/api/v1/catalog", params={"q": "tata rice"})
    assert res_no.status_code == 200
    assert res_no.json() == []

    # Ensure household 2's product is never returned even on broad query
    res_all = catalog_client.get("/api/v1/catalog", params={"q": ""})
    assert res_all.status_code == 200
    seed_ids = {item["seed_product_id"] for item in res_all.json()}
    assert "OTHER-001" not in seed_ids
    assert seed_ids == {"DS-0001", "DF-0001", "DS-0050"}


# Case 5: GET /catalog/{id}/search-urls -> 5 urls, encoded, only the 5 allowed hosts.
def test_case_5_catalog_search_urls(catalog_client: TestClient) -> None:
    items = catalog_client.get("/api/v1/catalog", params={"q": "tata toor"}).json()
    cat_id = items[0]["id"]

    res = catalog_client.get(f"/api/v1/catalog/{cat_id}/search-urls")
    assert res.status_code == 200, res.text
    urls = res.json()
    assert len(urls) == 5

    by_platform = {u["platform"]: u["url"] for u in urls}
    assert set(by_platform.keys()) == {"amazon", "flipkart", "blinkit", "zepto", "instamart"}

    allowed_hosts = {
        "amazon": "www.amazon.in",
        "flipkart": "www.flipkart.com",
        "blinkit": "blinkit.com",
        "zepto": "www.zepto.com",
        "instamart": "www.swiggy.com",
    }
    for plat, url_str in by_platform.items():
        parsed = urlparse(url_str)
        assert parsed.scheme == "https"
        assert parsed.hostname == allowed_hosts[plat]
        assert " " not in url_str  # must be URL-encoded
        assert "Tata" in url_str or "tata" in url_str.lower()
        assert "600g" in url_str or "600" in url_str


# Case 6: POST /catalog/{id}/candidates: a non-product url is dropped.
# Brand + pack match ranks first; pack_matches is right at +-10%. Nothing is written to the DB.
def test_case_6_score_candidates_drops_non_product_and_ranks_and_writes_nothing(
    catalog_client: TestClient,
    engine: Engine,
) -> None:
    items = catalog_client.get("/api/v1/catalog", params={"q": "tata toor"}).json()
    cat_id = items[0]["id"]  # target_pack_weight_g = 600 (+-10% is 540g..660g)

    payload = {
        "results": [
            # Non-product search URL -> must be dropped
            {
                "platform": "amazon",
                "url": "https://www.amazon.in/s?k=toor+dal",
                "title": "Tata Sampann Toor Dal 600g",
                "price_paise": 12000,
                "pack_label": "600g",
            },
            # Weak candidate: no brand, pack outside +-10% (500g is < 540g)
            {
                "platform": "flipkart",
                "url": "https://www.flipkart.com/unbranded-toor-dal/p/itm123456?pid=DAL12345678",
                "title": "Unbranded Toor Dal Pouch",
                "price_paise": 9900,
                "pack_label": "500g",
            },
            # Boundary candidate: exact +10% (660g) with brand + name words -> ranks above weak
            {
                "platform": "blinkit",
                "url": "https://blinkit.com/prn/tata-sampann-toor-dal/prid/551910",
                "title": "Tata Sampann Unpolished Toor Arhar Dal",
                "price_paise": 13500,
                "pack_label": "660g",
            },
            # Lower -10% boundary (540g) without brand
            {
                "platform": "instamart",
                "url": "https://instamart.in/p/everyday-toor-dal-pouch-T6LJGMXRBD",
                "title": "Everyday Toor Dal",
                "price_paise": 11000,
                "pack_label": "540g",
            },
        ]
    }

    res = catalog_client.post(f"/api/v1/catalog/{cat_id}/candidates", json=payload)
    assert res.status_code == 200, res.text
    scored = res.json()

    # Non-product URL was dropped -> 3 candidates remain
    assert len(scored) == 3

    # Brand + pack match (Blinkit Tata Sampann 660g) ranks first
    assert scored[0]["platform"] == "blinkit"
    assert scored[0]["url"] == "https://blinkit.com/prn/tata-sampann-toor-dal/prid/551910"
    assert scored[0]["pack_matches"] is True

    # Instamart 540g is right at -10% boundary -> pack_matches is True
    by_plat = {c["platform"]: c for c in scored}
    assert by_plat["instamart"]["pack_matches"] is True
    # Flipkart 500g is outside +-10% of 600g -> pack_matches is False
    assert by_plat["flipkart"]["pack_matches"] is False

    # Nothing written to CustomListing
    with Session(engine) as s:
        listings = s.exec(select(CustomListing)).all()
        assert listings == []


def test_case_2_pack_parsing_rules() -> None:
    from app.sources.autofill import _extract_pack_label

    assert _extract_pack_label("200 Gram (Pack Of 2)") == "400g"
    assert _extract_pack_label("Pack of 3 x 200g") == "600g"
    assert _extract_pack_label("1 Kg") == "1kg"
    assert _extract_pack_label("Premium Walnuts") is None
    assert _extract_pack_label("500gm") == "500g"


def test_case_3_candidate_null_pack_when_unknown(catalog_client: TestClient) -> None:
    items = catalog_client.get("/api/v1/catalog", params={"q": "tata toor"}).json()
    cat_id = items[0]["id"]

    payload = {
        "results": [
            {
                "platform": "flipkart",
                "url": "https://www.flipkart.com/toor-dal/p/itm123456?pid=DAL12345678",
                "title": "Fresh Premium Toor Dal",
                "price_paise": 11000,
                "pack_label": None,
            }
        ]
    }
    res = catalog_client.post(f"/api/v1/catalog/{cat_id}/candidates", json=payload)
    assert res.status_code == 200, res.text
    scored = res.json()
    assert len(scored) == 1
    assert scored[0]["pack_label"] is None
    assert scored[0]["pack_matches"] is False


def test_case_4_candidate_brand_resolution(catalog_client: TestClient, engine: Engine) -> None:
    with Session(engine) as s:
        cat = CatalogProduct(
            household_id=1,
            seed_product_id="WALNUT-1",
            name="California Walnuts",
            brand="Happilo",
            category="dryfruits",
            family_key="walnuts",
            pack_label="500g",
            target_pack_weight_g=500,
        )
        s.add(cat)
        s.commit()
        s.refresh(cat)
        cat_id = cat.id

    payload = {
        "results": [
            {
                "platform": "amazon",
                "url": "https://www.amazon.in/dp/B000000001",
                "title": "Deluxe Walnut Kernels 200g",
                "price_paise": 25000,
            },
            {
                "platform": "amazon",
                "url": "https://www.amazon.in/dp/B000000002",
                "title": "Happilo Premium Walnuts 500g",
                "price_paise": 45000,
            },
        ]
    }
    res = catalog_client.post(f"/api/v1/catalog/{cat_id}/candidates", json=payload)
    assert res.status_code == 200, res.text
    scored = {c["url"]: c for c in res.json()}
    assert scored["https://www.amazon.in/dp/B000000001"]["brand"] == "Deluxe"
    assert scored["https://www.amazon.in/dp/B000000002"]["brand"] == "Happilo"


def test_case_6_free_text_search_urls_and_candidates(catalog_client: TestClient) -> None:
    res = catalog_client.get("/api/v1/catalog/search-urls", params={"q": "Sunflower Seeds 500g"})
    assert res.status_code == 200, res.text
    urls = res.json()
    assert len(urls) == 5
    by_plat = {u["platform"]: u["url"] for u in urls}
    assert "amazon" in by_plat
    assert "Sunflower" in by_plat["amazon"] or "sunflower" in by_plat["amazon"].lower()

    cand_payload = {
        "results": [
            {
                "platform": "amazon",
                "url": "https://www.amazon.in/dp/B09XYZ0001",
                "title": "True Elements Raw Sunflower Seeds 500g",
                "price_paise": 22000,
                "pack_label": "500g",
            }
        ]
    }
    score_res = catalog_client.post(
        "/api/v1/catalog/candidates",
        params={"q": "Sunflower Seeds", "pack": "500g"},
        json=cand_payload,
    )
    assert score_res.status_code == 200, score_res.text
    scored = score_res.json()
    assert len(scored) == 1
    assert scored[0]["title"] == "True Elements Raw Sunflower Seeds 500g"
    assert scored[0]["pack_matches"] is True
    assert scored[0]["pack_label"] == "500g"


def test_case_5_migration_0010_catalog_categories(engine: Engine) -> None:
    import importlib
    mig_mod = importlib.import_module("migrations.versions.0010_catalog_categories")
    mig_0010_upgrade = mig_mod.upgrade

    with Session(engine) as s:
        s.execute(
            sa.text(
                "INSERT INTO catalog_product "
                "(household_id, seed_product_id, name, brand, category, "
                "family_key, pack_label, target_pack_weight_g, suggestions_json, "
                "created_at, updated_at) "
                "VALUES (1, 'OLD-001', 'Kaju', 'Happilo', 'cashews', 'cashews', "
                "'500g', 500, '[]', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
        )
        s.execute(
            sa.text(
                "INSERT INTO custom_listing "
                "(household_id, listing_id, platform, sku, url, title, brand, "
                "pack_label, category, product_key, family_key, created_at) "
                "VALUES (1, 'cus-old-1', 'amazon', 'B001', "
                "'https://www.amazon.in/dp/B001', 'Old Cashews', 'Happilo', "
                "'500g', 'dry_fruits_nuts', 'old_cashews', 'cashews', "
                "CURRENT_TIMESTAMP)"
            )
        )
        s.commit()

    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            mig_0010_upgrade()
        conn.commit()

    with Session(engine) as s:
        cat = s.exec(select(CatalogProduct).where(CatalogProduct.seed_product_id == "OLD-001")).first()
        assert cat is not None
        assert cat.category == "dryfruits"
        assert cat.name == "Kaju"

        listing = s.exec(select(CustomListing).where(CustomListing.listing_id == "cus-old-1")).first()
        assert listing is not None
        assert listing.category == "dryfruits"
        assert listing.title == "Old Cashews"
