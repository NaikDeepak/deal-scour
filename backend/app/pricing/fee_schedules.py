from dataclasses import dataclass
from typing import Literal

from app.core.money import Paise

Platform = Literal["amazon", "flipkart", "blinkit", "instamart", "zepto"]


@dataclass(frozen=True)
class FeeSchedule:
    platform: Platform
    delivery_fee: Paise
    # non-members: free when subtotal >= this; None = never free
    free_delivery_min: Paise | None
    # members: free when subtotal >= this; None = use free_delivery_min
    member_free_delivery_min: Paise | None = None
    handling_fee: Paise = 0
    platform_fee: Paise = 0
    small_cart_below: Paise | None = None  # small-cart fee charged when subtotal < this
    small_cart_fee: Paise = 0

    def __post_init__(self) -> None:
        for field_name in ("delivery_fee", "handling_fee", "platform_fee", "small_cart_fee"):
            val = getattr(self, field_name)
            if isinstance(val, bool) or not isinstance(val, int):
                raise TypeError(f"{field_name} must be int paise, got {type(val).__name__}")
        for opt_field in ("free_delivery_min", "member_free_delivery_min", "small_cart_below"):
            val = getattr(self, opt_field)
            if val is not None and (isinstance(val, bool) or not isinstance(val, int)):
                raise TypeError(f"{opt_field} must be int paise or None, got {type(val).__name__}")


@dataclass(frozen=True)
class FeeBreakdown:
    delivery: Paise
    handling: Paise
    platform: Paise
    small_cart: Paise
    surge: Paise

    def __post_init__(self) -> None:
        for field_name in ("delivery", "handling", "platform", "small_cart", "surge"):
            val = getattr(self, field_name)
            if isinstance(val, bool) or not isinstance(val, int):
                raise TypeError(f"{field_name} must be int paise, got {type(val).__name__}")

    @property
    def total(self) -> Paise:
        return self.delivery + self.handling + self.platform + self.small_cart + self.surge


def order_fees(
    schedule: FeeSchedule,
    subtotal: Paise,
    is_member: bool,
    surge: Paise = 0,
) -> FeeBreakdown:
    """Calculate order-level fees based on subtotal, membership, and fee schedule.

    subtotal < 0 or surge < 0 raises ValueError.
    subtotal == 0 returns all zero fees (no order is placed).
    Thresholds compare in paise using >=.
    """
    if isinstance(subtotal, bool) or not isinstance(subtotal, int):
        raise TypeError(f"subtotal must be int paise, got {type(subtotal).__name__}")
    if isinstance(surge, bool) or not isinstance(surge, int):
        raise TypeError(f"surge must be int paise, got {type(surge).__name__}")
    if subtotal < 0:
        raise ValueError(f"subtotal cannot be negative: {subtotal}")
    if surge < 0:
        raise ValueError(f"surge cannot be negative: {surge}")

    if subtotal == 0:
        return FeeBreakdown(
            delivery=0,
            handling=0,
            platform=0,
            small_cart=0,
            surge=0,
        )

    # Determine free delivery threshold
    if is_member:
        threshold = (
            schedule.member_free_delivery_min
            if schedule.member_free_delivery_min is not None
            else schedule.free_delivery_min
        )
    else:
        threshold = schedule.free_delivery_min

    delivery = 0 if threshold is not None and subtotal >= threshold else schedule.delivery_fee

    # Small cart fee charged when subtotal < small_cart_below
    small_cart = (
        schedule.small_cart_fee
        if schedule.small_cart_below is not None and subtotal < schedule.small_cart_below
        else 0
    )

    return FeeBreakdown(
        delivery=delivery,
        handling=schedule.handling_fee,
        platform=schedule.platform_fee,
        small_cart=small_cart,
        surge=surge,
    )


SAMPLE_SCHEDULES: dict[Platform, FeeSchedule] = {
    "amazon": FeeSchedule(
        platform="amazon",
        delivery_fee=4000,
        free_delivery_min=49900,
        member_free_delivery_min=0,
    ),
    "flipkart": FeeSchedule(
        platform="flipkart",
        delivery_fee=4000,
        free_delivery_min=49900,
        member_free_delivery_min=0,
    ),
    "instamart": FeeSchedule(
        platform="instamart",
        delivery_fee=2500,
        free_delivery_min=49900,
        member_free_delivery_min=19900,
        small_cart_below=9900,
        small_cart_fee=1500,
    ),
    "blinkit": FeeSchedule(
        platform="blinkit",
        delivery_fee=2500,
        free_delivery_min=19900,
        member_free_delivery_min=0,
        small_cart_below=9900,
        small_cart_fee=1500,
    ),
    "zepto": FeeSchedule(
        platform="zepto",
        delivery_fee=2500,
        free_delivery_min=19900,
        member_free_delivery_min=0,
        small_cart_below=9900,
        small_cart_fee=1500,
    ),
}
