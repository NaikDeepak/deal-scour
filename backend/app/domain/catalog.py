import dataclasses
import importlib.resources
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from sqlmodel import Session, col, select

from app.core.money import Paise
from app.domain.models import PriceObservation
from app.pricing.fee_schedules import Platform
from app.pricing.landed import ItemPrice
from app.pricing.units import Pack, Unit, default_basis, parse_pack


@dataclass(frozen=True)
class SeedListing:
    id: str
    product_key: str
    family_key: str
    category: str
    title: str
    brand: str
    pack_label: str
    platform: Platform
    listed: Paise
    mrp: Paise
    member_discount: Paise
    eta_minutes: int
    is_instant: bool
    coupon_text: str | None
    url: str
    icon: str
    source: str

    @property
    def pack(self) -> Pack:
        return parse_pack(self.pack_label)

    def item_price(self) -> ItemPrice:
        return ItemPrice(
            listed=self.listed,
            mrp=self.mrp,
            member_price=self.listed - self.member_discount,
        )


@dataclass(frozen=True)
class CurrentListing:  # a SeedListing with the household's latest observation applied
    # listed/mrp/member_discount/eta replaced by observation values when one exists
    listing: SeedListing
    source: Literal["sample", "manual"]
    observed_at: datetime | None  # None for sample
    freshness: Literal["sample", "fresh", "ok", "stale"]
    in_stock: bool


def compute_freshness(
    platform: Platform | str,
    observed_at: datetime | None,
    now: datetime,
) -> Literal["sample", "fresh", "ok", "stale"]:
    if observed_at is None:
        return "sample"
    if observed_at.tzinfo is None and now.tzinfo is not None:
        obs_dt = observed_at.replace(tzinfo=now.tzinfo)
    elif observed_at.tzinfo is not None and now.tzinfo is None:
        obs_dt = observed_at.replace(tzinfo=None)
    else:
        obs_dt = observed_at

    age = now - obs_dt
    is_quick = platform in {"blinkit", "instamart", "zepto"}
    fresh_limit = timedelta(hours=2) if is_quick else timedelta(hours=6)
    ok_limit = timedelta(hours=12) if is_quick else timedelta(hours=48)

    if age < fresh_limit:
        return "fresh"
    elif age < ok_limit:
        return "ok"
    else:
        return "stale"


def current_listings(
    session: Session,
    household_id: int,
    now: datetime,
) -> list[CurrentListing]:
    seed = load_seed()
    try:
        observations = session.exec(
            select(PriceObservation)
            .where(PriceObservation.household_id == household_id)
            .order_by(col(PriceObservation.observed_at).asc(), col(PriceObservation.id).asc())
        ).all()
    except Exception:
        observations = []
    latest_by_listing: dict[str, PriceObservation] = {}
    for o in observations:
        latest_by_listing[o.listing_id] = o

    result: list[CurrentListing] = []
    for item in seed:
        matched_obs = latest_by_listing.get(item.id)
        if matched_obs is None:
            result.append(
                CurrentListing(
                    listing=item,
                    source="sample",
                    observed_at=None,
                    freshness="sample",
                    in_stock=True,
                )
            )
        else:
            member_discount = (
                matched_obs.listed_paise - matched_obs.member_price_paise
                if matched_obs.member_price_paise is not None
                else 0
            )
            eta = matched_obs.eta_minutes if matched_obs.eta_minutes is not None else item.eta_minutes
            updated_listing = dataclasses.replace(
                item,
                listed=matched_obs.listed_paise,
                mrp=matched_obs.mrp_paise,
                member_discount=member_discount,
                eta_minutes=eta,
            )
            freshness = compute_freshness(item.platform, matched_obs.observed_at, now)
            source_val: Literal["sample", "manual"] = "manual" if matched_obs.source == "manual" else "sample"
            result.append(
                CurrentListing(
                    listing=updated_listing,
                    source=source_val,
                    observed_at=matched_obs.observed_at,
                    freshness=freshness,
                    in_stock=matched_obs.in_stock,
                )
            )
    return result


def load_seed() -> list[SeedListing]:
    """Load the prototype catalog seed data from the app.seed package."""
    catalog_path = importlib.resources.files("app.seed").joinpath("prototype_catalog.json")
    with catalog_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    listings: list[SeedListing] = []
    for item in data.get("listings", []):
        listing = SeedListing(
            id=item["id"],
            product_key=item["product_key"],
            family_key=item["family_key"],
            category=item["category"],
            title=item["title"],
            brand=item["brand"],
            pack_label=item["pack_label"],
            platform=item["platform"],
            listed=item["listed_paise"],
            mrp=item["mrp_paise"],
            member_discount=item["member_discount_paise"],
            eta_minutes=item["eta_minutes"],
            is_instant=item["is_instant"],
            coupon_text=item.get("coupon_text"),
            url=item["url"],
            icon=item["icon"],
            source=item["source"],
        )
        listings.append(listing)
    return listings


def rate_basis(category: str, unit: Unit) -> tuple[int, str]:
    """Return basis quantity and label for comparing unit rates.

    For dryfruits in grams, comparison basis is 100g.
    For everything else, returns default_basis(unit).
    """
    if category == "dryfruits" and unit == "g":
        return (100, "100g")
    return default_basis(unit)
