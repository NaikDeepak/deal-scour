from datetime import UTC, datetime, timedelta

import pytest
from sqlmodel import Session

from app.domain.catalog import (
    CurrentListing,
    compute_freshness,
    current_listings,
    load_seed,
)
from app.domain.models import Household, PriceObservation


def test_freshness_bands() -> None:
    now = datetime(2026, 10, 18, 12, 0, 0, tzinfo=UTC)

    # Sample when no observation
    assert compute_freshness("amazon", None, now) == "sample"
    assert compute_freshness("zepto", None, now) == "sample"

    # Amazon / Flipkart: fresh < 6h, ok < 48h, else stale
    # 5h old -> fresh
    t_5h = now - timedelta(hours=5)
    assert compute_freshness("amazon", t_5h, now) == "fresh"
    assert compute_freshness("flipkart", t_5h, now) == "fresh"

    # 7h old -> ok
    t_7h = now - timedelta(hours=7)
    assert compute_freshness("amazon", t_7h, now) == "ok"
    assert compute_freshness("flipkart", t_7h, now) == "ok"

    # 49h old -> stale
    t_49h = now - timedelta(hours=49)
    assert compute_freshness("amazon", t_49h, now) == "stale"
    assert compute_freshness("flipkart", t_49h, now) == "stale"

    # Quick commerce (zepto, blinkit, instamart): fresh < 2h, ok < 12h, else stale
    # 1h old -> fresh
    t_1h = now - timedelta(hours=1)
    assert compute_freshness("zepto", t_1h, now) == "fresh"
    assert compute_freshness("blinkit", t_1h, now) == "fresh"
    assert compute_freshness("instamart", t_1h, now) == "fresh"

    # 3h old -> ok
    t_3h = now - timedelta(hours=3)
    assert compute_freshness("zepto", t_3h, now) == "ok"
    assert compute_freshness("blinkit", t_3h, now) == "ok"
    assert compute_freshness("instamart", t_3h, now) == "ok"

    # 13h old -> stale
    t_13h = now - timedelta(hours=13)
    assert compute_freshness("zepto", t_13h, now) == "stale"
    assert compute_freshness("blinkit", t_13h, now) == "stale"
    assert compute_freshness("instamart", t_13h, now) == "stale"


def test_current_listings_no_observations(session: Session) -> None:
    now = datetime(2026, 10, 18, 12, 0, 0, tzinfo=UTC)
    listings = current_listings(session=session, household_id=1, now=now)
    assert len(listings) == 28

    for item in listings:
        assert isinstance(item, CurrentListing)
        assert item.source == "sample"
        assert item.observed_at is None
        assert item.freshness == "sample"
        assert item.in_stock is True


def test_current_listings_with_observation(session: Session) -> None:
    now = datetime(2026, 10, 18, 12, 0, 0, tzinfo=UTC)
    obs = PriceObservation(
        household_id=1,
        listing_id="stp-4",
        listed_paise=64900,
        mrp_paise=89000,
        member_price_paise=62900,
        in_stock=True,
        eta_minutes=None,  # should keep seed eta
        source="manual",
        observed_at=now - timedelta(hours=1),
    )
    session.add(obs)
    session.commit()

    listings = current_listings(session=session, household_id=1, now=now)
    stp_4 = next(item for item in listings if item.listing.id == "stp-4")
    assert stp_4.source == "manual"
    assert stp_4.freshness == "fresh"
    assert stp_4.in_stock is True
    assert stp_4.observed_at == now - timedelta(hours=1)
    assert stp_4.listing.listed == 64900
    assert stp_4.listing.mrp == 89000
    # member_discount = listed - member_price = 64900 - 62900 = 2000
    assert stp_4.listing.member_discount == 2000
    # Seed eta retained because observation eta_minutes was None
    seed_stp_4 = next(x for x in load_seed() if x.id == "stp-4")
    assert stp_4.listing.eta_minutes == seed_stp_4.eta_minutes


def test_current_listings_latest_observation_wins(session: Session) -> None:
    t0 = datetime(2026, 10, 18, 8, 0, 0, tzinfo=UTC)
    t1 = datetime(2026, 10, 18, 10, 0, 0, tzinfo=UTC)
    now = datetime(2026, 10, 18, 12, 0, 0, tzinfo=UTC)

    obs1 = PriceObservation(
        household_id=1,
        listing_id="stp-4",
        listed_paise=67000,
        mrp_paise=89000,
        member_price_paise=65000,
        in_stock=True,
        observed_at=t0,
    )
    obs2 = PriceObservation(
        household_id=1,
        listing_id="stp-4",
        listed_paise=64900,
        mrp_paise=89000,
        member_price_paise=62900,
        in_stock=True,
        observed_at=t1,
    )
    session.add(obs1)
    session.add(obs2)
    session.commit()

    listings = current_listings(session=session, household_id=1, now=now)
    stp_4 = next(item for item in listings if item.listing.id == "stp-4")
    assert stp_4.listing.listed == 64900
    assert stp_4.listing.member_discount == 2000
    assert stp_4.observed_at == t1


def test_current_listings_household_isolation(session: Session) -> None:
    now = datetime(2026, 10, 18, 12, 0, 0, tzinfo=UTC)
    session.add(Household(id=2, name="Other", pincode="411018"))
    session.commit()
    # Insert for household 2 directly
    obs_h2 = PriceObservation(
        household_id=2,
        listing_id="stp-4",
        listed_paise=50000,
        mrp_paise=89000,
        member_price_paise=48000,
        in_stock=True,
        observed_at=now,
    )
    session.add(obs_h2)
    session.commit()

    # Query for household 1 -> unaffected
    listings_h1 = current_listings(session=session, household_id=1, now=now)
    stp_4_h1 = next(item for item in listings_h1 if item.listing.id == "stp-4")
    assert stp_4_h1.source == "sample"
    assert stp_4_h1.freshness == "sample"
    assert stp_4_h1.listing.listed == 69500

    # Query for household 2 -> affected
    listings_h2 = current_listings(session=session, household_id=2, now=now)
    stp_4_h2 = next(item for item in listings_h2 if item.listing.id == "stp-4")
    assert stp_4_h2.source == "manual"
    assert stp_4_h2.listing.listed == 50000


def test_current_listings_out_of_stock(session: Session) -> None:
    now = datetime(2026, 10, 18, 12, 0, 0, tzinfo=UTC)
    obs = PriceObservation(
        household_id=1,
        listing_id="stp-4",
        listed_paise=64900,
        mrp_paise=89000,
        member_price_paise=62900,
        in_stock=False,
        observed_at=now,
    )
    session.add(obs)
    session.commit()

    listings = current_listings(session=session, household_id=1, now=now)
    stp_4 = next(item for item in listings if item.listing.id == "stp-4")
    assert stp_4.in_stock is False


def test_case_12_latest_observation_tiebreak_higher_id_wins(session: Session) -> None:
    # (12) Latest observation = max (observed_at, id): with identical observed_at,
    # the higher id (inserted later) wins.
    t_same = datetime(2026, 10, 18, 10, 0, 0, tzinfo=UTC)
    now = datetime(2026, 10, 18, 12, 0, 0, tzinfo=UTC)

    obs1 = PriceObservation(
        household_id=1,
        listing_id="stp-4",
        listed_paise=60000,
        mrp_paise=89000,
        member_price_paise=58000,
        in_stock=True,
        observed_at=t_same,
    )
    obs2 = PriceObservation(
        household_id=1,
        listing_id="stp-4",
        listed_paise=55000,
        mrp_paise=89000,
        member_price_paise=53000,
        in_stock=True,
        observed_at=t_same,
    )
    session.add(obs1)
    session.commit()
    session.refresh(obs1)

    session.add(obs2)
    session.commit()
    session.refresh(obs2)

    assert obs2.id is not None and obs1.id is not None
    assert obs2.id > obs1.id

    listings = current_listings(session=session, household_id=1, now=now)
    stp_4 = next(item for item in listings if item.listing.id == "stp-4")
    # Higher id (obs2) wins even though observed_at is identical
    assert stp_4.listing.listed == 55000
    assert stp_4.listing.member_discount == 2000


def test_case_13_freshness_timezone_normalization() -> None:
    # (13) Freshness: normalize observed_at and now to UTC before subtracting
    # (if tz-aware, convert to UTC; if naive, treat as UTC). Never drop an offset without converting.
    from datetime import timezone

    ist = timezone(timedelta(hours=5, minutes=30))
    # 15:30 IST is 10:00 UTC
    obs_ist = datetime(2026, 10, 18, 15, 30, 0, tzinfo=ist)
    now_utc = datetime(2026, 10, 18, 12, 0, 0, tzinfo=UTC)

    # For Amazon (fresh < 6h, ok < 48h): 2h age is fresh
    assert compute_freshness("amazon", obs_ist, now_utc) == "fresh"

    # For quick commerce (zepto: fresh < 2h, ok < 12h): 2h old is ok (not fresh)
    assert compute_freshness("zepto", obs_ist, now_utc) == "ok"

    # Also test naive observed_at: treated as UTC
    obs_naive = datetime(2026, 10, 18, 11, 0, 0)
    assert compute_freshness("amazon", obs_naive, now_utc) == "fresh"
    assert compute_freshness("zepto", obs_naive, now_utc) == "fresh"

    # Also test naive now: treated as UTC
    now_naive = datetime(2026, 10, 18, 12, 0, 0)
    assert compute_freshness("amazon", obs_ist, now_naive) == "fresh"


def test_case_14_db_error_propagates() -> None:
    # (14) REMOVE the catch-all try/except around the observation query in catalog.py.
    # DB errors must propagate (500), never silently fall back to sample prices (AGENTS.md invariant 6).
    from unittest.mock import MagicMock

    mock_session = MagicMock(spec=Session)
    mock_session.exec.side_effect = RuntimeError("Database connection lost")

    now = datetime(2026, 10, 18, 12, 0, 0, tzinfo=UTC)
    with pytest.raises(RuntimeError, match="Database connection lost"):
        current_listings(session=mock_session, household_id=1, now=now)
