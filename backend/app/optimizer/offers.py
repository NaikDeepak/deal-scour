from app.core.money import Paise, pct_of
from app.optimizer.contract import DEFAULT_MULTIPLIER_BP, Offer, Order


def eligible_subtotal(offer: Offer, order: Order) -> Paise:
    """Calculate the subtotal of lines in the order that are eligible for the offer."""
    if offer.eligible_categories is None:
        return order.subtotal
    return sum(line.total for line in order.lines if line.category in offer.eligible_categories)


def face_value(offer: Offer, eligible: Paise) -> Paise:
    """Calculate the face value discount of the offer given the eligible subtotal."""
    if offer.kind == "flat":
        return offer.value if eligible >= offer.min_order else 0
    elif offer.kind == "pct_cap":
        if eligible >= offer.min_order:
            discount = pct_of(eligible, offer.rate_bp)
            return min(discount, offer.cap) if offer.cap is not None else discount
        return 0
    elif offer.kind == "tiered":
        matched_val: Paise = 0
        for min_ord, val in offer.tiers:
            if eligible >= min_ord:
                matched_val = val
        return matched_val
    return 0


def effective_value(offer: Offer, face: Paise) -> Paise:
    """Calculate the effective value of an offer after applying value_type multipliers.

    Floors result towards zero.
    """
    multiplier_bp = (
        offer.multiplier_bp
        if offer.multiplier_bp is not None
        else DEFAULT_MULTIPLIER_BP[offer.value_type]
    )
    return (face * multiplier_bp) // 10000
