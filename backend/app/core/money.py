from decimal import Decimal, InvalidOperation

Paise = int


def rupees(amount: str | int) -> Paise:
    """Parse a rupee amount into integer paise.

    Accepts an integer or string with up to 2 decimal places and optional commas.
    Floats raise TypeError. Empty or non-numeric strings, or strings with more than
    2 decimal places raise ValueError.
    """
    if isinstance(amount, bool) or not isinstance(amount, (str, int)):
        raise TypeError(f"amount must be str or int, got {type(amount).__name__}")

    if isinstance(amount, int):
        return amount * 100

    cleaned = amount.strip().replace(",", "")
    if not cleaned:
        raise ValueError("amount cannot be empty")

    if "e" in cleaned.lower():
        raise ValueError(f"invalid amount: {amount}")

    try:
        d = Decimal(cleaned)
    except InvalidOperation:
        raise ValueError(f"invalid amount: {amount}") from None

    if not d.is_finite():
        raise ValueError(f"invalid amount: {amount}")

    exp = d.as_tuple().exponent
    if isinstance(exp, int) and exp < -2:
        raise ValueError(f"more than 2 decimals in {amount}")

    return int(d * 100)


def _format_indian_number(n: int) -> str:
    s = str(n)
    if len(s) <= 3:
        return s
    last3 = s[-3:]
    remaining = s[:-3]
    chunks: list[str] = []
    while len(remaining) > 2:
        chunks.append(remaining[-2:])
        remaining = remaining[:-2]
    if remaining:
        chunks.append(remaining)
    chunks.reverse()
    return ",".join(chunks) + "," + last3


def format_inr(paise: Paise) -> str:
    """Format paise as an INR currency string using Indian digit grouping.

    Paise is shown only when non-zero. Float raises TypeError.
    """
    if isinstance(paise, bool) or not isinstance(paise, int):
        raise TypeError(f"paise must be int, got {type(paise).__name__}")

    sign = "-" if paise < 0 else ""
    abs_paise = abs(paise)
    rupees_part = abs_paise // 100
    paise_part = abs_paise % 100

    formatted_rupees = _format_indian_number(rupees_part)
    if paise_part > 0:
        return f"{sign}₹{formatted_rupees}.{paise_part:02d}"
    return f"{sign}₹{formatted_rupees}"


def pct_of(paise: Paise, rate_bp: int) -> Paise:
    """Calculate percentage of paise using basis points (1000 bp = 10%).

    Result is floored towards zero. Negative rate_bp raises ValueError.
    Floats raise TypeError.
    """
    if isinstance(paise, bool) or not isinstance(paise, int):
        raise TypeError(f"paise must be int, got {type(paise).__name__}")
    if isinstance(rate_bp, bool) or not isinstance(rate_bp, int):
        raise TypeError(f"rate_bp must be int, got {type(rate_bp).__name__}")
    if rate_bp < 0:
        raise ValueError("rate_bp cannot be negative")

    product = paise * rate_bp
    if product >= 0:
        return product // 10000
    return -((-product) // 10000)
