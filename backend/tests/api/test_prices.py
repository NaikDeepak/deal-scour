from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel

from app.api.v1.baskets import router as baskets_router
from app.api.v1.deals import router as deals_router
from app.api.v1.lists import router as lists_router
from app.api.v1.offers import router as offers_router
from app.api.v1.plans import router as plans_router
from app.api.v1.prices import router as prices_router
from app.core import clock
from app.core.db import create_db_engine, get_session
from app.domain.models import Household, PriceObservation


@pytest.fixture
def prices_client(engine: Engine) -> Generator[TestClient, None, None]:
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


def test_case_1_no_observations_deals_identical(prices_client: TestClient) -> None:
    # 1. No observations → deals identical to today
    # (all price_source "sample", freshness "sample", in_stock true).
    resp = prices_client.get("/api/v1/deals")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 28
    for deal in data["deals"]:
        assert deal["price_source"] == "sample"
        assert deal["freshness"] == "sample"
        assert deal["observed_at"] is None
        assert deal["in_stock"] is True


def test_case_2_observe_stp4_deals_and_plans(prices_client: TestClient) -> None:
    # 2. Observe stp-4 (amazon Fortune 5L) listed 64900, mrp 89000, member 62900
    # → deals stp-4 unit_price 62900 (Prime on), price_source "manual", freshness "fresh".
    # Exact need fortune_sunlite_oil_5l in /plans → line_total 62900.
    post_resp = prices_client.post(
        "/api/v1/prices",
        json={
            "listing_id": "stp-4",
            "listed_paise": 64900,
            "mrp_paise": 89000,
            "member_price_paise": 62900,
            "in_stock": True,
        },
    )
    assert post_resp.status_code == 201, post_resp.text
    obs_data = post_resp.json()
    assert obs_data["listing_id"] == "stp-4"
    assert obs_data["listed_paise"] == 64900

    deals_resp = prices_client.get("/api/v1/deals")
    assert deals_resp.status_code == 200
    deals_by_id = {d["id"]: d for d in deals_resp.json()["deals"]}
    stp_4 = deals_by_id["stp-4"]
    assert stp_4["unit_price_paise"] == 62900
    assert stp_4["price_source"] == "manual"
    assert stp_4["freshness"] == "fresh"
    assert stp_4["in_stock"] is True

    plans_resp = prices_client.post(
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
    plans_data = plans_resp.json()
    base_orders = plans_data["baseline"]["orders"]
    # Should pick stp-4 (amazon) at 62900 vs stp-5 (flipkart) which is 72500
    amazon_order = next(o for o in base_orders if o["platform"] == "amazon")
    oil_line = next(line for line in amazon_order["lines"] if line["line_id"] == "oil")
    assert oil_line["listing_id"] == "stp-4"
    assert oil_line["unit_price_paise"] == 62900
    assert oil_line["line_total_paise"] == 62900
    assert oil_line["price_source"] == "manual"
    assert oil_line["freshness"] == "fresh"


def test_case_3_two_observations_latest_wins_and_get_prices(
    prices_client: TestClient,
) -> None:
    # 3. Two observations → the latest wins. GET /prices?listing_id=stp-4 lists both, newest first.
    r1 = prices_client.post(
        "/api/v1/prices",
        json={
            "listing_id": "stp-4",
            "listed_paise": 67000,
            "mrp_paise": 89000,
            "member_price_paise": 65000,
        },
    )
    assert r1.status_code == 201

    r2 = prices_client.post(
        "/api/v1/prices",
        json={
            "listing_id": "stp-4",
            "listed_paise": 64900,
            "mrp_paise": 89000,
            "member_price_paise": 62900,
        },
    )
    assert r2.status_code == 201

    get_resp = prices_client.get("/api/v1/prices?listing_id=stp-4")
    assert get_resp.status_code == 200, get_resp.text
    obs_list = get_resp.json()
    assert len(obs_list) == 2
    # Newest first
    assert obs_list[0]["listed_paise"] == 64900
    assert obs_list[1]["listed_paise"] == 67000

    deals_resp = prices_client.get("/api/v1/deals")
    stp_4 = next(d for d in deals_resp.json()["deals"] if d["id"] == "stp-4")
    assert stp_4["unit_price_paise"] == 62900


def test_case_4_freshness_bands_frozen_clock(
    engine: Engine,
) -> None:
    # 4. Freshness bands with a frozen clock:
    # amazon observation 5 h old → fresh, 7 h → ok, 49 h → stale.
    # Zepto observation 3 h old → ok, 13 h → stale.
    frozen_now = datetime(2026, 10, 18, 12, 0, 0, tzinfo=UTC)

    app = FastAPI()
    app.include_router(prices_router, prefix="/api/v1")
    app.include_router(deals_router, prefix="/api/v1")

    def override_get_session() -> Generator[Session, None, None]:
        with Session(engine) as s:
            yield s

    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[clock.now] = lambda: frozen_now

    with Session(engine) as session:
        # Amazon: stp-4
        # 5h old:
        session.add(
            PriceObservation(
                household_id=1,
                listing_id="stp-4",
                listed_paise=64900,
                mrp_paise=89000,
                observed_at=frozen_now - timedelta(hours=5),
            )
        )
        # Zepto: stp-6 (Fortune 1L on zepto)
        session.add(
            PriceObservation(
                household_id=1,
                listing_id="stp-6",  # zepto
                listed_paise=14200,
                mrp_paise=17500,
                observed_at=frozen_now - timedelta(hours=3),
            )
        )
        session.commit()

    with TestClient(app) as client:
        deals = {d["id"]: d for d in client.get("/api/v1/deals").json()["deals"]}
        assert deals["stp-4"]["freshness"] == "fresh"
        assert deals["stp-6"]["freshness"] == "ok"

    # Now update observed_at: amazon 7h, zepto 13h
    with Session(engine) as session:
        session.exec(sa.delete(PriceObservation))
        session.add(
            PriceObservation(
                household_id=1,
                listing_id="stp-4",
                listed_paise=64900,
                mrp_paise=89000,
                observed_at=frozen_now - timedelta(hours=7),
            )
        )
        session.add(
            PriceObservation(
                household_id=1,
                listing_id="stp-6",
                listed_paise=14200,
                mrp_paise=17500,
                observed_at=frozen_now - timedelta(hours=13),
            )
        )
        session.commit()

    with TestClient(app) as client:
        deals = {d["id"]: d for d in client.get("/api/v1/deals").json()["deals"]}
        assert deals["stp-4"]["freshness"] == "ok"
        assert deals["stp-6"]["freshness"] == "stale"

    # Now amazon 49h -> stale
    with Session(engine) as session:
        session.exec(sa.delete(PriceObservation))
        session.add(
            PriceObservation(
                household_id=1,
                listing_id="stp-4",
                listed_paise=64900,
                mrp_paise=89000,
                observed_at=frozen_now - timedelta(hours=49),
            )
        )
        session.commit()

    with TestClient(app) as client:
        deals = {d["id"]: d for d in client.get("/api/v1/deals").json()["deals"]}
        assert deals["stp-4"]["freshness"] == "stale"


def test_case_5_out_of_stock_plans_and_deals(prices_client: TestClient) -> None:
    # 5. Out of stock: observe stp-4 in_stock: false
    # → /plans for fortune_sunlite_oil_5l uses stp-5 (flipkart). Deals still list stp-4 with in_stock false.
    # If every listing of an exact need is out of stock → that line is unpriced.
    prices_client.post(
        "/api/v1/prices",
        json={
            "listing_id": "stp-4",
            "listed_paise": 64900,
            "mrp_paise": 89000,
            "in_stock": False,
        },
    )

    # Deals still list stp-4 with in_stock: false
    deals = {d["id"]: d for d in prices_client.get("/api/v1/deals").json()["deals"]}
    assert deals["stp-4"]["in_stock"] is False

    # Plans for fortune_sunlite_oil_5l uses stp-5 (flipkart)
    p_resp = prices_client.post(
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
    assert p_resp.status_code == 200
    p_data = p_resp.json()
    cheapest = next(p for p in p_data["plans"] if p["label"] == "cheapest_now")
    flipkart_order = next(o for o in cheapest["orders"] if o["platform"] == "flipkart")
    line = flipkart_order["lines"][0]
    assert line["listing_id"] == "stp-5"

    # Now observe stp-5 also out of stock
    prices_client.post(
        "/api/v1/prices",
        json={
            "listing_id": "stp-5",
            "listed_paise": 72500,
            "mrp_paise": 89000,
            "in_stock": False,
        },
    )

    # All listings for fortune_sunlite_oil_5l are out of stock -> unpriced!
    p_resp2 = prices_client.post(
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
    assert p_resp2.status_code == 200
    p2_data = p_resp2.json()
    assert "oil" in p2_data["baseline"]["unpriced"]
    for p in p2_data["plans"]:
        assert "oil" in p["unpriced"]


def test_case_6_household_isolation(prices_client: TestClient, session: Session) -> None:
    # 6. Household isolation: an observation by household 2 (inserted directly)
    # doesn't affect household 1's deals or plans.
    session.add(Household(id=2, name="Other", pincode="411018"))
    session.add(
        PriceObservation(
            household_id=2,
            listing_id="stp-4",
            listed_paise=40000,
            mrp_paise=89000,
            member_price_paise=35000,
            in_stock=True,
            observed_at=datetime.now(UTC),
        )
    )
    session.commit()

    deals = {d["id"]: d for d in prices_client.get("/api/v1/deals").json()["deals"]}
    # Household 1 should still see sample price (69500)
    assert deals["stp-4"]["price_source"] == "sample"
    assert deals["stp-4"]["listed_paise"] == 69500


def test_case_7_validation(prices_client: TestClient) -> None:
    # 7. Validation: unknown listing_id, listed 0, mrp < listed, member > listed, negative eta → 422.
    valid = {
        "listing_id": "stp-4",
        "listed_paise": 64900,
        "mrp_paise": 89000,
        "member_price_paise": 62900,
        "eta_minutes": 120,
    }

    # Unknown listing_id
    b_unknown = dict(valid, listing_id="unknown-999")
    assert prices_client.post("/api/v1/prices", json=b_unknown).status_code == 422

    # listed 0
    b_listed_0 = dict(valid, listed_paise=0)
    assert prices_client.post("/api/v1/prices", json=b_listed_0).status_code == 422

    # mrp < listed
    b_mrp = dict(valid, mrp_paise=50000, listed_paise=60000)
    assert prices_client.post("/api/v1/prices", json=b_mrp).status_code == 422

    # member > listed
    b_member = dict(valid, member_price_paise=70000, listed_paise=60000, mrp_paise=80000)
    assert prices_client.post("/api/v1/prices", json=b_member).status_code == 422

    # negative eta
    b_eta = dict(valid, eta_minutes=-10)
    assert prices_client.post("/api/v1/prices", json=b_eta).status_code == 422


def test_case_8_plans_response_lines_carry_price_source_freshness(
    prices_client: TestClient,
) -> None:
    # 8. Plans response lines carry price_source / freshness matching the deals view.
    prices_client.post(
        "/api/v1/prices",
        json={
            "listing_id": "stp-4",
            "listed_paise": 64900,
            "mrp_paise": 89000,
            "member_price_paise": 62900,
        },
    )

    plans_resp = prices_client.post(
        "/api/v1/plans",
        json={
            "needs": [
                {
                    "line_id": "oil",
                    "product_key": "fortune_sunlite_oil_5l",
                    "qty": 1,
                }
            ],
            "members": ["amazon"],
        },
    )
    assert plans_resp.status_code == 200
    plan_data = plans_resp.json()
    order = plan_data["plans"][0]["orders"][0]
    line = order["lines"][0]
    assert line["price_source"] == "manual"
    assert line["freshness"] == "fresh"


def test_case_9_baskets_copy_current_price(prices_client: TestClient) -> None:
    # 9. Baskets created from a saved-list plan (existing flow) copy the current price into basket_line.
    # 1. Create shopping list
    l_resp = prices_client.post(
        "/api/v1/lists",
        json={"name": "Pantry Run", "kind": "quick"},
    )
    assert l_resp.status_code == 201
    list_id = l_resp.json()["id"]

    # 2. Add need for oil
    n_resp = prices_client.post(
        f"/api/v1/lists/{list_id}/needs",
        json={
            "line_id": "oil",
            "product_key": "fortune_sunlite_oil_5l",
            "qty": 1,
            "lock_platform": "amazon",
        },
    )
    assert n_resp.status_code == 201

    # 3. Add observation for stp-4
    prices_client.post(
        "/api/v1/prices",
        json={
            "listing_id": "stp-4",
            "listed_paise": 64900,
            "mrp_paise": 89000,
            "member_price_paise": 62900,
        },
    )

    # 4. Plan list
    p_resp = prices_client.post(
        f"/api/v1/lists/{list_id}/plan",
        json={"members": ["amazon"]},
    )
    assert p_resp.status_code == 200
    plan_run_id = p_resp.json()["plan_run_id"]

    # 5. Accept plan
    accept_resp = prices_client.post(
        f"/api/v1/plan-runs/{plan_run_id}/accept",
        json={"label": "cheapest_now"},
    )
    assert accept_resp.status_code == 200
    baskets = accept_resp.json()
    assert len(baskets) == 1
    lines = baskets[0]["lines"]
    assert len(lines) == 1
    oil_bline = lines[0]
    assert oil_bline["listing_id"] == "stp-4"
    assert oil_bline["unit_price_paise"] == 62900
    assert oil_bline["line_total_paise"] == 62900


def test_case_10_migration_0003_upgrade_and_downgrade(tmp_path: Path) -> None:
    # 10. Migration 0003 upgrades from 0002 with data intact.
    db_file = tmp_path / "upgrade_0003_test.db"
    db_url = f"sqlite:///{db_file.resolve()}"

    alembic_cfg = Config(str(Path(__file__).parent.parent.parent / "alembic.ini"))
    alembic_cfg.set_main_option("sqlalchemy.url", db_url)
    alembic_cfg.set_main_option(
        "script_location", str(Path(__file__).parent.parent.parent / "migrations")
    )

    # 1. Upgrade to 0002_baskets
    command.upgrade(alembic_cfg, "0002_baskets")

    engine = create_db_engine(db_file)
    with Session(engine) as session:
        # Insert a basket
        basket_table = SQLModel.metadata.tables["basket"]
        plan_run_table = SQLModel.metadata.tables["plan_run"]
        session.exec(
            sa.insert(plan_run_table).values(
                id=1,
                household_id=1,
                request_json="{}",
                response_json="{}",
                created_at=datetime.now(UTC),
            )
        )
        session.exec(
            sa.insert(basket_table).values(
                id=1,
                household_id=1,
                plan_run_id=1,
                platform="amazon",
                status="ready",
                planned_net_paise=50000,
                created_at=datetime.now(UTC),
            )
        )
        session.commit()
    engine.dispose()

    # 2. Upgrade to 0003_price_observation
    command.upgrade(alembic_cfg, "0003_price_observation")

    # 3. Verify basket still intact and price_observation table exists
    engine2 = create_db_engine(db_file)
    inspector = sa.inspect(engine2)
    assert "price_observation" in inspector.get_table_names()

    with Session(engine2) as session:
        basket_table = SQLModel.metadata.tables["basket"]
        row = session.exec(sa.select(basket_table).where(basket_table.c.id == 1)).first()
        assert row is not None
        assert row.platform == "amazon"
        assert row.planned_net_paise == 50000

        # Insert a price_observation
        obs_table = SQLModel.metadata.tables["price_observation"]
        session.exec(
            sa.insert(obs_table).values(
                id=1,
                household_id=1,
                listing_id="stp-4",
                listed_paise=64900,
                mrp_paise=89000,
                member_price_paise=62900,
                in_stock=True,
                source="manual",
                observed_at=datetime.now(UTC),
            )
        )
        session.commit()
        obs_row = session.exec(sa.select(obs_table).where(obs_table.c.id == 1)).first()
        assert obs_row is not None
        assert obs_row.listed_paise == 64900

    engine2.dispose()

    # 4. Downgrade back to 0002_baskets
    command.downgrade(alembic_cfg, "0002_baskets")
    engine3 = create_db_engine(db_file)
    inspector3 = sa.inspect(engine3)
    assert "price_observation" not in inspector3.get_table_names()
    engine3.dispose()
