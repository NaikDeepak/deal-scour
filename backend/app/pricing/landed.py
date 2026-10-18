from dataclasses import dataclass

from app.core.money import Paise


@dataclass(frozen=True)
class ItemPrice:
    listed: Paise
    mrp: Paise
    member_price: Paise | None = None  # used only when is_member
    item_coupon: Paise = 0  # off each unit

    def __post_init__(self) -> None:
        for field_name in ("listed", "mrp", "item_coupon"):
            val = getattr(self, field_name)
            if isinstance(val, bool) or not isinstance(val, int):
                raise TypeError(f"{field_name} must be int paise, got {type(val).__name__}")
        if self.member_price is not None and (
            isinstance(self.member_price, bool) or not isinstance(self.member_price, int)
        ):
            msg = f"member_price must be int paise or None, got {type(self.member_price).__name__}"
            raise TypeError(msg)


def unit_price(p: ItemPrice, is_member: bool) -> Paise:
    """Calculate effective unit price after member discount and item coupon, floored at 0."""
    base = p.member_price if is_member and p.member_price is not None else p.listed
    return max(0, base - p.item_coupon)


def line_price(p: ItemPrice, qty: int, is_member: bool) -> Paise:
    """Calculate line price for a quantity of items.

    qty < 1 raises ValueError. Order-level fees are not included here (ADR-011).
    """
    if isinstance(qty, bool) or not isinstance(qty, int):
        raise TypeError(f"qty must be an integer, got {type(qty).__name__}")
    if qty < 1:
        raise ValueError(f"qty must be >= 1, got {qty}")
    return unit_price(p, is_member) * qty


def discount_bp(p: ItemPrice, is_member: bool) -> int:
    """Calculate discount vs MRP in basis points (1000 bp = 10%) on unit price only.

    Result is floored. If mrp <= 0 or unit price >= mrp, returns 0. Never negative.
    """
    if p.mrp <= 0:
        return 0

    up = unit_price(p, is_member)
    discount = p.mrp - up
    if discount <= 0:
        return 0

    return (discount * 10000) // p.mrp
