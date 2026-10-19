from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import Session, select

from app.core import clock
from app.core.db import current_household_id, get_session
from app.core.money import Paise
from app.domain.catalog import current_listings
from app.domain.models import CustomListing, ListingWatch, PriceObservation
from app.pricing.fee_schedules import Platform

router = APIRouter()

HouseholdIdDep = Annotated[int, Depends(current_household_id)]
SessionDep = Annotated[Session, Depends(get_session)]
ClockDep = Annotated[datetime, Depends(clock.now)]


class DealFeedItem(BaseModel):
    listing_id: str
    title: str
    brand: str
    pack_label: str
    platform: Platform
    url: str
    category: str
    family_key: str
    icon: str
    listed_paise: Paise
    mrp_paise: Paise
    target_paise: Paise | None = None
    avg_30d_paise: Paise | None = None
    low_30d_paise: Paise | None = None
    saving_pct: float
    reasons: list[str]
    observed_at: datetime
    freshness: str


class DealFeedResponse(BaseModel):
    count: int
    deals: list[DealFeedItem]


@router.get("/deals/feed", response_model=DealFeedResponse)
def get_deals_feed(
    household_id: HouseholdIdDep,
    session: SessionDep,
    now: ClockDep,
) -> DealFeedResponse:
    # 1. Fetch watches and custom listings for this household
    watches = session.exec(
        select(ListingWatch).where(ListingWatch.household_id == household_id)
    ).all()
    watch_by_id = {w.listing_id: w for w in watches}

    custom_listings = session.exec(
        select(CustomListing).where(
            CustomListing.household_id == household_id,
            CustomListing.archived.is_(False),  # type: ignore[attr-defined]
        )
    ).all()
    custom_ids = {cl.listing_id for cl in custom_listings}

    # 2. Get current listings (seed + custom) for household
    all_curr = current_listings(session, household_id, now)

    # 3. Filter to in-stock, fresh/ok, non-sample prices for watched or custom items
    eligible = [
        c
        for c in all_curr
        if (c.listing.id in custom_ids or c.listing.id in watch_by_id)
        and c.in_stock is True
        and c.freshness in ("fresh", "ok")
        and c.source != "sample"
        and c.observed_at is not None
    ]

    since_30d = now - timedelta(days=30)
    deals: list[DealFeedItem] = []

    for item in eligible:
        listing_id = item.listing.id
        watch = watch_by_id.get(listing_id)

        # Observations for this listing in last 30 days
        obs_30d = session.exec(
            select(PriceObservation).where(
                PriceObservation.household_id == household_id,
                PriceObservation.listing_id == listing_id,
                PriceObservation.observed_at >= since_30d,
                PriceObservation.source != "sample",
            )
        ).all()

        low_30d: Paise | None = None
        high_30d: Paise | None = None
        avg_30d: Paise | None = None
        if obs_30d:
            prices = [o.listed_paise for o in obs_30d]
            low_30d = min(prices)
            high_30d = max(prices)
            avg_30d = (sum(prices) + len(prices) // 2) // len(prices)

        reasons: list[str] = []
        current_price = item.listing.listed

        # Reason 1: below_target
        if watch and watch.target_paise is not None and current_price <= watch.target_paise:
            reasons.append("below_target")

        # Reason 2: low_30d (current <= 30-day low, >= 3 observations, and price movement in window)
        if (
            len(obs_30d) >= 3
            and low_30d is not None
            and high_30d is not None
            and high_30d > low_30d
            and current_price <= low_30d
        ):
            reasons.append("low_30d")

        # Reason 3: under_avg (>= 15% under 30-day average, integer money math)
        if avg_30d is not None and avg_30d > 0 and (current_price * 100 <= avg_30d * 85):
            reasons.append("under_avg")

        if not reasons:
            continue

        # Calculate saving %
        if avg_30d is not None and avg_30d > current_price:
            saving_pct = round((avg_30d - current_price) / avg_30d * 100, 1)
        elif item.listing.mrp > current_price:
            saving_pct = round((item.listing.mrp - current_price) / item.listing.mrp * 100, 1)
        elif watch and watch.target_paise and watch.target_paise > current_price:
            saving_pct = round((watch.target_paise - current_price) / watch.target_paise * 100, 1)
        else:
            saving_pct = 0.0

        deals.append(
            DealFeedItem(
                listing_id=listing_id,
                title=item.listing.title,
                brand=item.listing.brand,
                pack_label=item.listing.pack_label,
                platform=item.listing.platform,
                url=item.listing.url,
                category=item.listing.category,
                family_key=item.listing.family_key,
                icon=item.listing.icon,
                listed_paise=current_price,
                mrp_paise=item.listing.mrp,
                target_paise=watch.target_paise if watch else None,
                avg_30d_paise=avg_30d,
                low_30d_paise=low_30d,
                saving_pct=saving_pct,
                reasons=reasons,
                observed_at=item.observed_at or now,
                freshness=item.freshness,
            )
        )

    # Sort by saving % descending
    deals.sort(key=lambda d: d.saving_pct, reverse=True)

    return DealFeedResponse(
        count=len(deals),
        deals=deals,
    )
