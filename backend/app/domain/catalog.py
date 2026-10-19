import dataclasses
import importlib.resources
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, cast

from sqlmodel import Session, col, select

from app.core.money import Paise
from app.domain.models import CustomListing, PriceObservation
from app.pricing.fee_schedules import Platform
from app.pricing.landed import ItemPrice
from app.pricing.units import Pack, Unit, default_basis, parse_pack


def to_utc(dt: datetime) -> datetime:
    """Normalize dt to UTC.

    If naive, assume UTC. If timezone-aware, convert to UTC without dropping offset.
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


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
    source: Literal["sample", "manual", "fetcher", "extension"]
    observed_at: datetime | None  # None for sample
    freshness: Literal["sample", "fresh", "ok", "stale"]
    in_stock: bool


def _map_observation_source(raw: str) -> Literal["sample", "manual", "fetcher", "extension"]:
    if raw == "manual":
        return "manual"
    if raw == "fetcher":
        return "fetcher"
    if raw == "extension":
        return "extension"
    return "sample"


def compute_freshness(
    platform: Platform | str,
    observed_at: datetime | None,
    now: datetime,
) -> Literal["sample", "fresh", "ok", "stale"]:
    if observed_at is None:
        return "sample"
    obs_dt = to_utc(observed_at)
    now_dt = to_utc(now)

    age = now_dt - obs_dt
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
    observations = session.exec(
        select(PriceObservation)
        .where(PriceObservation.household_id == household_id)
        .order_by(col(PriceObservation.observed_at).asc(), col(PriceObservation.id).asc())
    ).all()
    latest_by_listing: dict[str, PriceObservation] = {}
    for o in observations:
        prev = latest_by_listing.get(o.listing_id)
        if prev is None:
            latest_by_listing[o.listing_id] = o
        else:
            prev_key = (to_utc(prev.observed_at), prev.id if prev.id is not None else 0)
            curr_key = (to_utc(o.observed_at), o.id if o.id is not None else 0)
            if curr_key >= prev_key:
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
            source_val = _map_observation_source(matched_obs.source)
            result.append(
                CurrentListing(
                    listing=updated_listing,
                    source=source_val,
                    observed_at=matched_obs.observed_at,
                    freshness=freshness,
                    in_stock=matched_obs.in_stock,
                )
            )

    custom_listings = session.exec(
        select(CustomListing).where(
            CustomListing.household_id == household_id,
            CustomListing.archived.is_(False),  # type: ignore[attr-defined]
        )
    ).all()

    for custom in custom_listings:
        matched_obs = latest_by_listing.get(custom.listing_id)
        if matched_obs is None:
            # Custom listing's price comes ONLY from observations
            continue

        is_instant = custom.platform in {"blinkit", "instamart", "zepto"}
        member_discount = (
            matched_obs.listed_paise - matched_obs.member_price_paise
            if matched_obs.member_price_paise is not None
            else 0
        )
        eta = (
            matched_obs.eta_minutes
            if matched_obs.eta_minutes is not None
            else (15 if is_instant else 1440)
        )
        custom_seed_listing = SeedListing(
            id=custom.listing_id,
            product_key=custom.product_key,
            family_key=custom.family_key,
            category=custom.category,
            title=custom.title,
            brand=custom.brand,
            pack_label=custom.pack_label,
            platform=cast(Platform, custom.platform),
            listed=matched_obs.listed_paise,
            mrp=matched_obs.mrp_paise,
            member_discount=member_discount,
            eta_minutes=eta,
            is_instant=is_instant,
            coupon_text=None,
            url=custom.url,
            icon=custom.icon,
            source="manual",
        )
        freshness = compute_freshness(custom.platform, matched_obs.observed_at, now)
        custom_source_val = _map_observation_source(matched_obs.source)
        result.append(
            CurrentListing(
                listing=custom_seed_listing,
                source=custom_source_val,
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


def all_listings(
    session: Session,
    household_id: int,
) -> list[SeedListing]:
    """Return all seed listings plus non-archived custom listings for this household."""
    seed = load_seed()
    custom_listings = session.exec(
        select(CustomListing).where(
            CustomListing.household_id == household_id,
            CustomListing.archived.is_(False),  # type: ignore[attr-defined]
        )
    ).all()

    result: list[SeedListing] = list(seed)
    for custom in custom_listings:
        is_instant = custom.platform in {"blinkit", "instamart", "zepto"}
        result.append(
            SeedListing(
                id=custom.listing_id,
                product_key=custom.product_key,
                family_key=custom.family_key,
                category=custom.category,
                title=custom.title,
                brand=custom.brand,
                pack_label=custom.pack_label,
                platform=cast(Platform, custom.platform),
                listed=0,
                mrp=0,
                member_discount=0,
                eta_minutes=15 if is_instant else 1440,
                is_instant=is_instant,
                coupon_text=None,
                url=custom.url,
                icon=custom.icon,
                source="manual",
            )
        )
    return result

