from dataclasses import dataclass

from app.core.money import Paise
from app.optimizer.evaluate import PlanResult
from app.pricing.fee_schedules import Platform


@dataclass(frozen=True)
class Candidate:
    listing_id: str
    platform: Platform
    unit_price: Paise  # already membership-adjusted (pricing.landed.unit_price)
    eta_minutes: int


@dataclass(frozen=True)
class NeedLine:
    line_id: str
    category: str
    qty: int
    candidates: tuple[Candidate, ...]
    need_by_minutes: int | None = None  # candidate allowed only if eta_minutes <= need_by_minutes
    lock_platform: Platform | None = None  # if set, only candidates on this platform are allowed

    def __post_init__(self) -> None:
        if not isinstance(self.candidates, tuple):
            object.__setattr__(self, "candidates", tuple(self.candidates))
        if self.qty < 1:
            raise ValueError(f"qty must be >= 1, got {self.qty}")


@dataclass(frozen=True)
class PlanSettings:
    max_orders_per_platform: int = 4
    max_iterations: int = 300


DEFAULT_PLAN_SETTINGS = PlanSettings()


@dataclass(frozen=True)
class PlannedLine:
    line_id: str
    listing_id: str
    platform: Platform
    unit_price: Paise
    qty: int


@dataclass(frozen=True)
class Plan:
    # Each inner tuple is one order; all lines in it share a platform
    orders: tuple[tuple[PlannedLine, ...], ...]
    result: PlanResult  # evaluate_plan of exactly these orders
    unpriced: tuple[str, ...]  # line_ids with no allowed candidate (sorted)

    def __post_init__(self) -> None:
        if not isinstance(self.orders, tuple):
            object.__setattr__(self, "orders", tuple(tuple(o) for o in self.orders))
        else:
            if any(not isinstance(o, tuple) for o in self.orders):
                object.__setattr__(
                    self,
                    "orders",
                    tuple(tuple(o) if not isinstance(o, tuple) else o for o in self.orders),
                )
        if not isinstance(self.unpriced, tuple):
            object.__setattr__(self, "unpriced", tuple(self.unpriced))
