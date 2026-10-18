import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from app.core.money import Paise

Unit = Literal["g", "ml", "pc"]

_UNIT_MAP: dict[str, tuple[Unit, int]] = {
    # grams / kg
    "kg": ("g", 1000),
    "kgs": ("g", 1000),
    "kilo": ("g", 1000),
    "kilogram": ("g", 1000),
    "kilograms": ("g", 1000),
    "g": ("g", 1),
    "gm": ("g", 1),
    "gms": ("g", 1),
    "gram": ("g", 1),
    "grams": ("g", 1),
    # ml / litres
    "l": ("ml", 1000),
    "ltr": ("ml", 1000),
    "ltrs": ("ml", 1000),
    "litre": ("ml", 1000),
    "litres": ("ml", 1000),
    "liter": ("ml", 1000),
    "liters": ("ml", 1000),
    "ml": ("ml", 1),
    "mls": ("ml", 1),
    "millilitre": ("ml", 1),
    "millilitres": ("ml", 1),
    "milliliter": ("ml", 1),
    "milliliters": ("ml", 1),
    # pieces
    "pc": ("pc", 1),
    "pcs": ("pc", 1),
    "piece": ("pc", 1),
    "pieces": ("pc", 1),
    "unit": ("pc", 1),
    "units": ("pc", 1),
    "count": ("pc", 1),
    "ct": ("pc", 1),
}


@dataclass(frozen=True)
class Pack:
    qty: int  # in grams, millilitres or pieces
    unit: Unit

    def __post_init__(self) -> None:
        if isinstance(self.qty, bool) or not isinstance(self.qty, int):
            raise TypeError(f"qty must be int, got {type(self.qty).__name__}")
        if self.qty <= 0:
            raise ValueError(f"qty must be positive, got {self.qty}")
        if self.unit not in ("g", "ml", "pc"):
            raise ValueError(f"invalid unit: {self.unit}")


def parse_pack(label: str) -> Pack:
    """Parse pack label string into a Pack object with canonical units (g, ml, pc).

    Case-insensitive, optional spaces. Multipliers like '2 x 500g' are multiplied out.
    'pack of 6' parses as 6 pieces.
    Unparseable, zero or negative amounts raise ValueError.
    """
    s = " ".join(label.strip().lower().split())
    if not s:
        raise ValueError("Pack label cannot be empty")

    if s.startswith("pack of "):
        rest = s[8:].strip()
        if rest.isdigit():
            qty = int(rest)
            if qty <= 0:
                raise ValueError(f"Invalid pack quantity in: {label}")
            return Pack(qty=qty, unit="pc")
        s = rest

    # Multiplier pattern: e.g. "2 x 500g", "2x500g"
    mult_match = re.match(r"^(\d+)\s*[xX*]\s*(.+)$", s)
    if mult_match:
        multiplier = int(mult_match.group(1))
        if multiplier <= 0:
            raise ValueError(f"Multiplier must be positive in: {label}")
        sub_pack = parse_pack(mult_match.group(2))
        return Pack(qty=multiplier * sub_pack.qty, unit=sub_pack.unit)

    single_match = re.match(r"^([0-9]+(?:\.[0-9]+)?)\s*([a-zA-Z]+)$", s)
    if not single_match:
        raise ValueError(f"Unparseable pack label: {label}")

    num_str = single_match.group(1)
    unit_str = single_match.group(2)

    if unit_str not in _UNIT_MAP:
        raise ValueError(f"Unknown unit '{unit_str}' in pack label: {label}")

    canonical_unit, factor = _UNIT_MAP[unit_str]
    decimal_qty = Decimal(num_str) * factor
    if decimal_qty != int(decimal_qty):
        raise ValueError(f"Pack quantity must be a whole integer: {label}")

    qty = int(decimal_qty)
    if qty <= 0:
        raise ValueError(f"Pack quantity must be positive: {label}")

    return Pack(qty=qty, unit=canonical_unit)


def default_basis(unit: Unit) -> tuple[int, str]:
    """Return default basis quantity and unit label for unit rate comparison."""
    if unit == "g":
        return (1000, "kg")
    if unit == "ml":
        return (1000, "L")
    if unit == "pc":
        return (1, "pc")
    raise ValueError(f"Unknown unit: {unit}")


def unit_rate(price: Paise, pack: Pack, basis_qty: int | None = None) -> Paise:
    """Calculate paise per basis_qty of pack.unit, rounded HALF UP to whole paise.

    basis_qty defaults to default_basis(pack.unit)[0].
    """
    if isinstance(price, bool) or not isinstance(price, int):
        raise TypeError(f"price must be int paise, got {type(price).__name__}")

    if basis_qty is not None:
        if isinstance(basis_qty, bool) or not isinstance(basis_qty, int):
            raise TypeError(f"basis_qty must be int, got {type(basis_qty).__name__}")
        if basis_qty <= 0:
            raise ValueError(f"basis_qty must be positive, got {basis_qty}")
    else:
        basis_qty = default_basis(pack.unit)[0]

    if pack.qty <= 0:
        raise ValueError(f"pack.qty must be positive, got {pack.qty}")

    rate = (Decimal(price * basis_qty) / Decimal(pack.qty)).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )
    return int(rate)
