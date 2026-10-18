import importlib.resources
import json
from dataclasses import dataclass

from app.core.money import Paise
from app.pricing.fee_schedules import Platform
from app.pricing.landed import ItemPrice
from app.pricing.units import Pack, Unit, default_basis, parse_pack


@dataclass(frozen=True)
class SeedListing:
    id: str
    product_key: str
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
