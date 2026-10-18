"""Parse product pages fetched from Amazon and Flipkart into prices (ADR-004, personal low-volume fetching).

Pure functions: HTML in, `PageResult` out. No network here; `fetcher.py` does the polite fetching.
"""

import html as html_lib
import json
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from app.core.money import Paise


class PageBlockedError(Exception):
    """The site answered with a bot check instead of the product page. Never try to get around it."""


class PageParseError(Exception):
    """The page loaded but the price could not be found (layout change or unusual product page)."""


@dataclass(frozen=True)
class PageResult:
    listed_paise: Paise
    mrp_paise: Paise | None  # None when the page shows no struck-through MRP (product sells at MRP)
    in_stock: bool
    title: str | None


def _paise(amount: str) -> Paise:
    try:
        value = Decimal(amount.replace(",", "").replace("₹", "").strip())
    except InvalidOperation as exc:
        raise PageParseError(f"not a price: {amount!r}") from exc
    if value <= 0:
        raise PageParseError(f"non-positive price: {amount!r}")
    return int((value * 100).to_integral_value())


def _text(fragment: str) -> str:
    return re.sub(r"\s+", " ", html_lib.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


_AMAZON_BLOCK = re.compile(
    r"validateCaptcha|Type the characters you see|api-services-support@amazon\.com", re.I
)


def parse_amazon_product(page: str) -> PageResult:
    if _AMAZON_BLOCK.search(page):
        raise PageBlockedError("amazon bot check")
    title_m = re.search(r'id="productTitle"[^>]*>(.*?)</span>', page, re.S)
    title = _text(title_m.group(1)) if title_m else None

    core_at = page.find('id="corePriceDisplay_desktop_feature_div"')
    core = page[core_at : core_at + 20000] if core_at >= 0 else ""

    # Buy-box price: structured value first, then the visible price inside the core price block.
    price_m = re.search(r'"priceAmount":\s*([\d.]+)', page) or re.search(
        r'class="a-price-whole">([\d,]+)', core
    )
    avail_m = re.search(r'id="availability"[^>]*>(.*?)</div>', page, re.S)
    availability = _text(avail_m.group(1)).lower() if avail_m else ""
    unavailable = any(s in availability for s in ("currently unavailable", "out of stock", "unavailable"))
    if price_m is None:
        if unavailable:
            raise PageParseError("amazon: out of stock and no price shown")
        raise PageParseError("amazon: price not found")
    listed = _paise(price_m.group(1))

    mrp_m = re.search(r"basisPrice.{0,800}?a-offscreen\">([^<]+)<", core, re.S) or re.search(
        r"M\.R\.P\.?:?\s*(?:<[^>]+>\s*)*₹\s?([\d,]+(?:\.\d+)?)", core
    )
    mrp = _paise(mrp_m.group(1)) if mrp_m else None
    if mrp is not None and mrp < listed:
        mrp = None  # a per-unit or unrelated figure; never report MRP below the price
    return PageResult(listed_paise=listed, mrp_paise=mrp, in_stock=not unavailable, title=title)


_FLIPKART_BLOCK = re.compile(r"<title>\s*(Access Denied|Are you a human|Flipkart - Verify)", re.I)


def parse_flipkart_product(page: str) -> PageResult:
    if _FLIPKART_BLOCK.search(page):
        raise PageBlockedError("flipkart bot check")
    product: dict[str, object] | None = None
    for block in re.findall(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', page, re.S):
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            continue
        for entry in data if isinstance(data, list) else [data]:
            if isinstance(entry, dict) and entry.get("@type") == "Product":
                product = entry
                break
        if product:
            break
    if product is None:
        raise PageParseError("flipkart: no Product data on page")
    offers = product.get("offers")
    offer = offers[0] if isinstance(offers, list) and offers else offers
    if not isinstance(offer, dict) or offer.get("price") in (None, ""):
        raise PageParseError("flipkart: no offer price")
    listed = _paise(str(offer["price"]))
    in_stock = "instock" in str(offer.get("availability", "")).lower()

    mrp_m = re.search(r'"mrp":\s*(\d+(?:\.\d+)?)', page)
    mrp = _paise(mrp_m.group(1)) if mrp_m else None
    if mrp is not None and mrp < listed:
        mrp = None
    name = product.get("name")
    title = str(name) if name else None
    return PageResult(listed_paise=listed, mrp_paise=mrp, in_stock=in_stock, title=title)
