from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.core.money import Paise
from app.domain.catalog import load_seed, rate_basis
from app.pricing.fee_schedules import SAMPLE_SCHEDULES, Platform
from app.pricing.landed import discount_bp, unit_price
from app.pricing.units import unit_rate

router = APIRouter()

_VALID_PLATFORMS: set[str] = {"amazon", "flipkart", "blinkit", "instamart", "zepto"}
_VALID_SORTS: set[str] = {"unit_rate", "price", "discount", "eta"}


class DealOut(BaseModel):
    id: str
    product_key: str
    family_key: str
    category: str
    title: str
    brand: str
    platform: Platform
    pack_label: str
    icon: str
    url: str
    coupon_text: str | None
    source: str
    is_member: bool
    listed_paise: Paise
    mrp_paise: Paise
    unit_price_paise: Paise
    discount_bp: int
    unit_rate_paise: Paise
    rate_basis_label: str
    delivery_fee_paise: Paise
    free_delivery_min_paise: int | None
    eta_minutes: int
    is_instant: bool
    is_best_in_product: bool
    is_best_in_family: bool


class DealsResponse(BaseModel):
    count: int
    deals: list[DealOut]


@router.get("/deals", response_model=DealsResponse)
def get_deals(
    members: str = Query("amazon,instamart,flipkart"),
    category: str | None = Query(None),
    platform: str | None = Query(None),
    family: str | None = Query(None),
    q: str | None = Query(None),
    sort: str = Query("unit_rate"),
) -> DealsResponse:
    # Validate sort
    if sort not in _VALID_SORTS:
        raise HTTPException(status_code=422, detail=f"Invalid sort option: {sort}")

    # Validate platform
    if platform is not None and platform not in _VALID_PLATFORMS:
        raise HTTPException(status_code=422, detail=f"Invalid platform: {platform}")

    # Parse and validate members
    active_members: set[str] = set()
    stripped_members = members.strip()
    if stripped_members:
        member_list = [m.strip() for m in stripped_members.split(",")]
        for m in member_list:
            if m not in _VALID_PLATFORMS:
                raise HTTPException(status_code=422, detail=f"Invalid platform in members: {m}")
        active_members = set(member_list)

    listings = load_seed()

    # Compute deals for all listings
    computed_deals: list[DealOut] = []
    min_rate_by_product: dict[str, int] = {}
    min_rate_by_family: dict[str, int] = {}

    for listing in listings:
        is_mem = listing.platform in active_members
        ip = listing.item_price()
        up = unit_price(ip, is_mem)
        dbp = discount_bp(ip, is_mem)
        basis_qty, basis_label = rate_basis(listing.category, listing.pack.unit)
        ur = unit_rate(up, listing.pack, basis_qty)

        schedule = SAMPLE_SCHEDULES[listing.platform]
        free_min: int | None
        if is_mem and schedule.member_free_delivery_min is not None:
            free_min = schedule.member_free_delivery_min
        else:
            free_min = schedule.free_delivery_min

        delivery_fee = 0 if free_min == 0 else schedule.delivery_fee

        if (
            listing.product_key not in min_rate_by_product
            or ur < min_rate_by_product[listing.product_key]
        ):
            min_rate_by_product[listing.product_key] = ur

        if (
            listing.family_key not in min_rate_by_family
            or ur < min_rate_by_family[listing.family_key]
        ):
            min_rate_by_family[listing.family_key] = ur

        deal = DealOut(
            id=listing.id,
            product_key=listing.product_key,
            family_key=listing.family_key,
            category=listing.category,
            title=listing.title,
            brand=listing.brand,
            platform=listing.platform,
            pack_label=listing.pack_label,
            icon=listing.icon,
            url=listing.url,
            coupon_text=listing.coupon_text,
            source=listing.source,
            is_member=is_mem,
            listed_paise=listing.listed,
            mrp_paise=listing.mrp,
            unit_price_paise=up,
            discount_bp=dbp,
            unit_rate_paise=ur,
            rate_basis_label=basis_label,
            delivery_fee_paise=delivery_fee,
            free_delivery_min_paise=free_min,
            eta_minutes=listing.eta_minutes,
            is_instant=listing.is_instant,
            is_best_in_product=False,  # Updated in second pass
            is_best_in_family=False,  # Updated in second pass
        )
        computed_deals.append(deal)

    # Set is_best_in_product and is_best_in_family based on global minimums
    for deal in computed_deals:
        if deal.unit_rate_paise == min_rate_by_product[deal.product_key]:
            deal.is_best_in_product = True
        if deal.unit_rate_paise == min_rate_by_family[deal.family_key]:
            deal.is_best_in_family = True

    # Filtering
    filtered_deals = computed_deals
    if category is not None:
        filtered_deals = [d for d in filtered_deals if d.category == category]
    if platform is not None:
        filtered_deals = [d for d in filtered_deals if d.platform == platform]
    if family is not None:
        filtered_deals = [d for d in filtered_deals if d.family_key == family]
    if q is not None:
        q_lower = q.lower()
        filtered_deals = [
            d
            for d in filtered_deals
            if q_lower in d.title.lower()
            or q_lower in d.brand.lower()
            or q_lower in d.category.lower()
        ]

    # Sorting
    if sort == "unit_rate":
        filtered_deals.sort(key=lambda d: (d.unit_rate_paise, d.id))
    elif sort == "price":
        filtered_deals.sort(key=lambda d: (d.unit_price_paise, d.id))
    elif sort == "discount":
        filtered_deals.sort(key=lambda d: (-d.discount_bp, d.id))
    elif sort == "eta":
        filtered_deals.sort(key=lambda d: (d.eta_minutes, d.id))

    return DealsResponse(count=len(filtered_deals), deals=filtered_deals)
