import gzip
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy.engine import Engine
from sqlmodel import Session, col, select

from app.api.v1.deals import router as deals_router
from app.domain.models import CustomListing, PriceObservation, SourceStatus
from app.sources.fetcher import refresh_due_listings

FIXTURES = Path(__file__).parent.parent / "fixtures" / "sources"


def _page(name: str) -> str:
    return gzip.decompress((FIXTURES / name).read_bytes()).decode("utf-8", errors="ignore")


@pytest.fixture
def amazon_fixture() -> str:
    return _page("amazon_dp_B072HG4WNC.html.gz")


@pytest.fixture
def flipkart_fixture() -> str:
    return _page("flipkart_p_JASHRN6FZUFHMESG.html.gz")


def _make_custom_listing(
    session: Session,
    household_id: int,
    listing_id: str,
    platform: str,
    sku: str,
    url: str,
    title: str = "Test Product",
    created_at: datetime | None = None,
) -> CustomListing:
    cl = CustomListing(
        household_id=household_id,
        listing_id=listing_id,
        platform=platform,
        sku=sku,
        url=url,
        title=title,
        brand="TestBrand",
        pack_label="500g",
        category="staples",
        product_key=f"pk_{listing_id}",
        family_key=f"fk_{listing_id}",
        created_at=created_at or datetime.now(UTC),
    )
    session.add(cl)
    session.commit()
    session.refresh(cl)
    return cl


def test_1_due_listings_polite_sleep_and_fixtures(
    engine: Engine,
    amazon_fixture: str,
    flipkart_fixture: str,
) -> None:
    now_dt = datetime(2026, 10, 19, 10, 0, 0, tzinfo=UTC)
    sleeps: list[float] = []

    with Session(engine) as session:
        _make_custom_listing(session, 1, "amz-1", "amazon", "B072HG4WNC", "https://amazon.in/dp/B072HG4WNC")
        _make_custom_listing(session, 1, "amz-2", "amazon", "B072HG4WND", "https://amazon.in/dp/B072HG4WND")
        _make_custom_listing(
            session, 1, "fk-1", "flipkart", "JASHRN6FZUFHMESG", "https://flipkart.com/p/JASHRN6FZUFHMESG"
        )

        urls_called: list[str] = []

        def fake_http_get(url: str) -> tuple[int, str]:
            urls_called.append(url)
            if "amazon" in url:
                return (200, amazon_fixture)
            return (200, flipkart_fixture)

        def fake_sleep(seconds: float) -> None:
            sleeps.append(seconds)

        report = refresh_due_listings(
            session,
            household_id=1,
            http_get=fake_http_get,
            now=lambda: now_dt,
            sleep=fake_sleep,
            interval_hours=6,
        )

        assert report.fetched == 3
        assert set(report.updated) == {"amz-1", "amz-2", "fk-1"}
        assert report.failed == []
        assert report.skipped_platforms == []

        # Between the two amazon calls, sleep must be called so same-platform gaps total >= 10s
        assert len(sleeps) >= 1
        assert sum(sleeps) >= 10.0

        # Observations created with source="fetcher"
        obs = session.exec(
            select(PriceObservation).where(
                PriceObservation.household_id == 1,
                PriceObservation.source == "fetcher",
            )
        ).all()
        assert len(obs) == 3
        obs_by_listing = {o.listing_id: o for o in obs}

        assert obs_by_listing["amz-1"].listed_paise == 180000
        assert obs_by_listing["amz-1"].mrp_paise == 180000  # no MRP in page -> max(listed, listed)
        assert obs_by_listing["amz-1"].in_stock is True

        assert obs_by_listing["fk-1"].listed_paise == 24000
        assert obs_by_listing["fk-1"].mrp_paise == 34900
        assert obs_by_listing["fk-1"].in_stock is True


def test_2_not_due_vs_due_interval(engine: Engine, amazon_fixture: str) -> None:
    now_dt = datetime(2026, 10, 19, 12, 0, 0, tzinfo=UTC)

    with Session(engine) as session:
        # Listing 1: observation 1h old (not due when interval=6)
        _make_custom_listing(session, 1, "amz-1h", "amazon", "B001", "https://amazon.in/dp/B001")
        session.add(
            PriceObservation(
                household_id=1,
                listing_id="amz-1h",
                listed_paise=10000,
                mrp_paise=10000,
                source="fetcher",
                observed_at=now_dt - timedelta(hours=1),
            )
        )

        # Listing 2: observation 7h old (due when interval=6)
        _make_custom_listing(session, 1, "amz-7h", "amazon", "B002", "https://amazon.in/dp/B002")
        session.add(
            PriceObservation(
                household_id=1,
                listing_id="amz-7h",
                listed_paise=12000,
                mrp_paise=12000,
                source="fetcher",
                observed_at=now_dt - timedelta(hours=7),
            )
        )
        session.commit()

        called: list[str] = []

        def fake_http_get(url: str) -> tuple[int, str]:
            called.append(url)
            return (200, amazon_fixture)

        report = refresh_due_listings(
            session,
            household_id=1,
            http_get=fake_http_get,
            now=lambda: now_dt,
            sleep=lambda s: None,
            interval_hours=6,
        )

        assert report.fetched == 1
        assert report.updated == ["amz-7h"]
        assert called == ["https://amazon.in/dp/B002"]


def test_3_mrp_fallback(engine: Engine) -> None:
    # Amazon page with no struck MRP -> observation MRP = max(listed, previous MRP)
    now_dt = datetime(2026, 10, 19, 12, 0, 0, tzinfo=UTC)
    page_without_mrp = (
        '<span id="productTitle">Product Without MRP</span>'
        '<div id="corePriceDisplay_desktop_feature_div"><span class="a-price-whole">500</span></div>'
    )

    with Session(engine) as session:
        _make_custom_listing(session, 1, "amz-prev-mrp", "amazon", "B003", "https://amazon.in/dp/B003")
        # Previous observation had MRP 60000
        session.add(
            PriceObservation(
                household_id=1,
                listing_id="amz-prev-mrp",
                listed_paise=45000,
                mrp_paise=60000,
                source="manual",
                observed_at=now_dt - timedelta(days=2),
            )
        )
        session.commit()

        report = refresh_due_listings(
            session,
            household_id=1,
            http_get=lambda url: (200, page_without_mrp),
            now=lambda: now_dt,
            sleep=lambda s: None,
            interval_hours=6,
        )

        assert report.fetched == 1
        assert report.updated == ["amz-prev-mrp"]

        latest_obs = session.exec(
            select(PriceObservation)
            .where(PriceObservation.listing_id == "amz-prev-mrp")
            .order_by(col(PriceObservation.observed_at).desc())
        ).first()
        assert latest_obs is not None
        assert latest_obs.listed_paise == 50000
        # MRP falls back to max(listed, previous MRP) = max(50000, 60000) = 60000
        assert latest_obs.mrp_paise == 60000


def test_4_blocked_three_failures_disables_platform_for_24h(
    engine: Engine,
    flipkart_fixture: str,
) -> None:
    now_dt = datetime(2026, 10, 19, 12, 0, 0, tzinfo=UTC)
    captcha_page = "<form action='/errors/validateCaptcha'>Type characters</form>"

    with Session(engine) as session:
        _make_custom_listing(session, 1, "amz-b1", "amazon", "B01", "https://amazon.in/dp/B01")
        _make_custom_listing(session, 1, "amz-b2", "amazon", "B02", "https://amazon.in/dp/B02")
        _make_custom_listing(session, 1, "amz-b3", "amazon", "B03", "https://amazon.in/dp/B03")
        _make_custom_listing(session, 1, "amz-b4", "amazon", "B04", "https://amazon.in/dp/B04")
        _make_custom_listing(session, 1, "fk-ok", "flipkart", "F01", "https://flipkart.com/p/F01")

        urls_called: list[str] = []

        def fake_http_get(url: str) -> tuple[int, str]:
            urls_called.append(url)
            if "amazon" in url:
                return (200, captcha_page)
            return (200, flipkart_fixture)

        report = refresh_due_listings(
            session,
            household_id=1,
            http_get=fake_http_get,
            now=lambda: now_dt,
            sleep=lambda s: None,
            interval_hours=6,
        )

        # 3 amazon failures, then amazon disabled, remaining amazon skipped, flipkart fetched
        assert "amazon" in report.skipped_platforms
        assert "fk-ok" in report.updated
        # amz-b4 should NOT have been fetched because amazon was disabled at 3 failures
        assert "https://amazon.in/dp/B04" not in urls_called

        # Status check
        amz_status = session.get(SourceStatus, "amazon")
        assert amz_status is not None
        assert amz_status.consecutive_failures == 3
        assert amz_status.disabled_until == now_dt + timedelta(hours=24)

        # Next run before 24h: amazon is skipped immediately
        urls_called.clear()
        report2 = refresh_due_listings(
            session,
            household_id=1,
            http_get=fake_http_get,
            now=lambda: now_dt + timedelta(hours=10),
            sleep=lambda s: None,
            interval_hours=6,
        )
        assert "amazon" in report2.skipped_platforms
        assert not any("amazon" in u for u in urls_called)

        # Next run after 24h: tried again!
        urls_called.clear()
        refresh_due_listings(
            session,
            household_id=1,
            http_get=fake_http_get,
            now=lambda: now_dt + timedelta(hours=25),
            sleep=lambda s: None,
            interval_hours=6,
        )
        assert any("amazon" in u for u in urls_called)


def test_5_success_resets_consecutive_failures(engine: Engine, amazon_fixture: str) -> None:
    now_dt = datetime(2026, 10, 19, 12, 0, 0, tzinfo=UTC)

    with Session(engine) as session:
        session.add(
            SourceStatus(
                platform="amazon",
                consecutive_failures=2,
                last_error="HTTP 500",
                last_success_at=now_dt - timedelta(days=1),
            )
        )
        _make_custom_listing(session, 1, "amz-s1", "amazon", "B05", "https://amazon.in/dp/B05")
        session.commit()

        report = refresh_due_listings(
            session,
            household_id=1,
            http_get=lambda url: (200, amazon_fixture),
            now=lambda: now_dt,
            sleep=lambda s: None,
            interval_hours=6,
        )

        assert report.updated == ["amz-s1"]
        amz_status = session.get(SourceStatus, "amazon")
        assert amz_status is not None
        assert amz_status.consecutive_failures == 0
        assert amz_status.last_error is None
        assert amz_status.last_success_at == now_dt


def test_6_parse_error_isolated_to_listing(engine: Engine, amazon_fixture: str) -> None:
    now_dt = datetime(2026, 10, 19, 12, 0, 0, tzinfo=UTC)
    bad_page = "<html><body>No price here</body></html>"

    with Session(engine) as session:
        _make_custom_listing(session, 1, "amz-bad", "amazon", "B06", "https://amazon.in/dp/B06")
        _make_custom_listing(session, 1, "amz-good", "amazon", "B07", "https://amazon.in/dp/B07")

        def fake_http_get(url: str) -> tuple[int, str]:
            if "B06" in url:
                return (200, bad_page)
            return (200, amazon_fixture)

        report = refresh_due_listings(
            session,
            household_id=1,
            http_get=fake_http_get,
            now=lambda: now_dt,
            sleep=lambda s: None,
            interval_hours=6,
        )

        assert report.updated == ["amz-good"]
        assert len(report.failed) == 1
        assert report.failed[0][0] == "amz-bad"
        # Platform was NOT disabled
        assert "amazon" not in report.skipped_platforms
        st = session.get(SourceStatus, "amazon")
        # Consecutive failures not incremented for platform by parse error
        assert st is None or st.consecutive_failures == 0


def test_7_never_fetches_quick_commerce_or_seed(engine: Engine) -> None:
    now_dt = datetime(2026, 10, 19, 12, 0, 0, tzinfo=UTC)

    with Session(engine) as session:
        _make_custom_listing(session, 1, "blk-1", "blinkit", "123", "https://blinkit.com/prn/item/prid/123")
        _make_custom_listing(session, 1, "zpt-1", "zepto", "a90ee928-85c8-47c1-ae14-c36199cc874b", "https://zepto.com/pn/item/pvid/a90ee928-85c8-47c1-ae14-c36199cc874b")
        _make_custom_listing(session, 1, "ist-1", "instamart", "999", "https://swiggy.com/instamart/item/999")

        urls_called: list[str] = []

        report = refresh_due_listings(
            session,
            household_id=1,
            http_get=lambda url: (urls_called.append(url) or (200, "")),
            now=lambda: now_dt,
            sleep=lambda s: None,
            interval_hours=6,
        )

        assert report.fetched == 0
        assert report.updated == []
        assert urls_called == []


def test_8_max_30_per_run_oldest_first(engine: Engine, amazon_fixture: str) -> None:
    base_time = datetime(2026, 10, 1, 12, 0, 0, tzinfo=UTC)
    now_dt = datetime(2026, 10, 19, 12, 0, 0, tzinfo=UTC)

    with Session(engine) as session:
        # Create 35 due listings with different creation / observation times
        for i in range(35):
            cl = _make_custom_listing(
                session,
                1,
                f"amz-batch-{i:02d}",
                "amazon",
                f"B{i:03d}",
                f"https://amazon.in/dp/B{i:03d}",
                created_at=base_time + timedelta(minutes=i),
            )
            # Give each an observation > 6 hours old, ordered so i=0 is oldest
            session.add(
                PriceObservation(
                    household_id=1,
                    listing_id=cl.listing_id,
                    listed_paise=10000,
                    mrp_paise=10000,
                    source="fetcher",
                    observed_at=base_time + timedelta(hours=i),
                )
            )
        session.commit()

        called: list[str] = []

        report = refresh_due_listings(
            session,
            household_id=1,
            http_get=lambda url: (called.append(url) or (200, amazon_fixture)),
            now=lambda: now_dt,
            sleep=lambda s: None,
            interval_hours=6,
        )

        assert report.fetched == 30
        assert len(report.updated) == 30
        # Oldest first: batch-00 through batch-29
        expected_ids = [f"amz-batch-{i:02d}" for i in range(30)]
        assert report.updated == expected_ids


def test_9_household_isolation(engine: Engine, amazon_fixture: str) -> None:
    now_dt = datetime(2026, 10, 19, 12, 0, 0, tzinfo=UTC)

    with Session(engine) as session:
        from app.domain.models import Household
        session.add(Household(id=2, name="Household 2", pincode="411018"))
        session.commit()

        _make_custom_listing(session, 1, "amz-hh1", "amazon", "B101", "https://amazon.in/dp/B101")
        _make_custom_listing(session, 2, "amz-hh2", "amazon", "B102", "https://amazon.in/dp/B102")

        called: list[str] = []

        report = refresh_due_listings(
            session,
            household_id=1,
            http_get=lambda url: (called.append(url) or (200, amazon_fixture)),
            now=lambda: now_dt,
            sleep=lambda s: None,
            interval_hours=6,
        )

        assert report.updated == ["amz-hh1"]
        assert called == ["https://amazon.in/dp/B101"]


def test_12_deals_show_fetched_price_with_price_source_fetcher(
    engine: Engine,
    amazon_fixture: str,
) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(deals_router, prefix="/api/v1")

    def override_get_session():
        with Session(engine) as s:
            yield s

    from app.core.db import current_household_id, get_session
    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[current_household_id] = lambda: 1

    now_dt = datetime(2026, 10, 19, 12, 0, 0, tzinfo=UTC)

    with Session(engine) as session:
        _make_custom_listing(session, 1, "amz-deal-1", "amazon", "B777", "https://amazon.in/dp/B777")
        refresh_due_listings(
            session,
            household_id=1,
            http_get=lambda url: (200, amazon_fixture),
            now=lambda: now_dt,
            sleep=lambda s: None,
            interval_hours=6,
        )

    with TestClient(app) as client:
        resp = client.get("/api/v1/deals")
        assert resp.status_code == 200
        deals = {d["id"]: d for d in resp.json()["deals"]}
        assert "amz-deal-1" in deals
        d = deals["amz-deal-1"]
        assert d["price_source"] == "fetcher"
        assert d["freshness"] == "fresh"
        assert d["listed_paise"] == 180000
