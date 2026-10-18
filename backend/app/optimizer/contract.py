from dataclasses import dataclass
from typing import Literal

from app.core.money import Paise
from app.pricing.fee_schedules import Platform

OfferKind = Literal["flat", "pct_cap", "tiered"]
ValueType = Literal["cash", "instant", "amazon_pay", "supercoins"]

DEFAULT_MULTIPLIER_BP: dict[ValueType, int] = {
    "cash": 10000,
    "instant": 10000,
    "amazon_pay": 10000,
    "supercoins": 8000,
}


@dataclass(frozen=True)
class Offer:
    id: str
    platform: Platform
    kind: OfferKind
    min_order: Paise = 0  # flat, pct_cap (tiered uses tiers)
    value: Paise = 0  # flat
    rate_bp: int = 0  # pct_cap
    cap: Paise | None = None  # pct_cap; None = uncapped
    tiers: tuple[tuple[Paise, Paise], ...] = ()  # tiered: ((min_order, value), ...)
    uses_left: int = 1
    stack_group: str = "platform_coupon"
    value_type: ValueType = "cash"
    multiplier_bp: int | None = None  # None -> DEFAULT_MULTIPLIER_BP[value_type]
    eligible_categories: frozenset[str] | None = None  # None = every category counts

    def __post_init__(self) -> None:
        if self.min_order < 0:
            raise ValueError(f"min_order cannot be negative, got {self.min_order}")
        if self.uses_left < 0:
            raise ValueError(f"uses_left cannot be negative, got {self.uses_left}")
        if self.multiplier_bp is not None and not (0 <= self.multiplier_bp <= 10000):
            raise ValueError(f"multiplier_bp must be 0..10000, got {self.multiplier_bp}")

        if self.kind not in ("flat", "pct_cap", "tiered"):
            raise ValueError(f"unknown offer kind: {self.kind}")

        if self.kind == "flat":
            if self.value <= 0:
                raise ValueError(f"flat offer value must be > 0, got {self.value}")
        elif self.kind == "pct_cap":
            if self.rate_bp <= 0 or self.rate_bp > 10000:
                raise ValueError(f"rate_bp must be 1..10000, got {self.rate_bp}")
            if self.cap is not None and self.cap <= 0:
                raise ValueError(f"cap must be > 0, got {self.cap}")
        elif self.kind == "tiered":
            if len(self.tiers) == 0:
                raise ValueError("tiered offer tiers cannot be empty")
            prev_min = -1
            prev_val = 0
            for min_ord, val in self.tiers:
                if min_ord <= prev_min:
                    raise ValueError("tiered minimums must be strictly increasing")
                if val <= prev_val:
                    raise ValueError("tiered values must be strictly increasing")
                if val <= 0:
                    raise ValueError("tiered value must be > 0")
                prev_min = min_ord
                prev_val = val


@dataclass(frozen=True)
class OrderLine:
    line_id: str
    category: str
    unit_price: Paise
    qty: int = 1

    def __post_init__(self) -> None:
        if isinstance(self.qty, bool) or not isinstance(self.qty, int):
            raise TypeError(f"qty must be an integer, got {type(self.qty).__name__}")
        if self.qty < 1:
            raise ValueError(f"qty must be >= 1, got {self.qty}")
        if isinstance(self.unit_price, bool) or not isinstance(self.unit_price, int):
            raise TypeError(f"unit_price must be int paise, got {type(self.unit_price).__name__}")
        if self.unit_price < 0:
            raise ValueError(f"unit_price cannot be negative, got {self.unit_price}")

    @property
    def total(self) -> Paise:
        return self.unit_price * self.qty


@dataclass(frozen=True)
class Order:
    platform: Platform
    lines: tuple[OrderLine, ...]
    is_member: bool
    surge: Paise = 0

    def __post_init__(self) -> None:
        if len(self.lines) == 0:
            raise ValueError("Order must have at least one line")
        if isinstance(self.surge, bool) or not isinstance(self.surge, int):
            raise TypeError(f"surge must be int paise, got {type(self.surge).__name__}")
        if self.surge < 0:
            raise ValueError(f"surge cannot be negative: {self.surge}")

    @property
    def subtotal(self) -> Paise:
        return sum(line.total for line in self.lines)
