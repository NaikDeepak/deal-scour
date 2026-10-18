import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

from app.pricing.fee_schedules import Platform

_SHORT_LINK_HOSTS: set[str] = {"amzn.in", "amzn.to", "fkrt.it"}
_SHORT_LINK_ERROR: str = (
    "Short links can't be read without opening them. "
    "Open the link in your browser and paste the full address."
)

_AMAZON_HOSTS: set[str] = {"amazon.in", "www.amazon.in", "m.amazon.in"}
_FLIPKART_HOSTS: set[str] = {"flipkart.com", "www.flipkart.com", "dl.flipkart.com"}
_BLINKIT_HOSTS: set[str] = {"blinkit.com", "www.blinkit.com"}
_ZEPTO_HOSTS: set[str] = {"zeptonow.com", "www.zeptonow.com", "zepto.com", "www.zepto.com"}
_INSTAMART_HOSTS: set[str] = {"swiggy.com", "www.swiggy.com"}


@dataclass(frozen=True)
class ProductRef:
    platform: Platform
    sku: str  # amazon ASIN | flipkart pid | blinkit prid | zepto pvid | instamart item id
    url: str  # canonical URL


def parse_product_url(url: str) -> ProductRef:
    url = url.strip()
    parsed = urlparse(url)

    host = (parsed.hostname or "").lower()

    # Short links check
    if host in _SHORT_LINK_HOSTS or (host == "dl.flipkart.com" and parsed.path.startswith("/s/")):
        raise ValueError(_SHORT_LINK_ERROR)

    if parsed.scheme.lower() != "https":
        raise ValueError(f"Only https URLs are supported, got: '{parsed.scheme}'")

    path = parsed.path

    # 1. Amazon
    if host in _AMAZON_HOSTS:
        # Match /dp/{ASIN}, /{slug}/dp/{ASIN}, /gp/product/{ASIN}, /gp/aw/d/{ASIN}
        m = re.match(
            r"^(?:/[^/]+)?/dp/([A-Za-z0-9]{10})(?:/.*)?$|"
            r"^/gp/product/([A-Za-z0-9]{10})(?:/.*)?$|"
            r"^/gp/aw/d/([A-Za-z0-9]{10})(?:/.*)?$",
            path,
        )
        if not m:
            raise ValueError(f"Could not extract a valid 10-character Amazon ASIN from URL: {url}")
        asin = (m.group(1) or m.group(2) or m.group(3)).upper()
        return ProductRef(
            platform="amazon",
            sku=asin,
            url=f"https://www.amazon.in/dp/{asin}",
        )

    # 2. Flipkart
    if host in _FLIPKART_HOSTS:
        # Path: /{slug}/p/{itm}
        m = re.match(r"^/([^/]+)/p/([^/?#]+)", path)
        if not m:
            raise ValueError(
                f"Could not extract product path '/{{slug}}/p/{{itm}}' from Flipkart URL: {url}"
            )
        slug, itm = m.group(1), m.group(2)
        qs = parse_qs(parsed.query)
        pids = qs.get("pid")
        if not pids or not pids[0]:
            raise ValueError(f"Flipkart URL is missing required 'pid' parameter: {url}")
        pid = pids[0]
        return ProductRef(
            platform="flipkart",
            sku=pid,
            url=f"https://www.flipkart.com/{slug}/p/{itm}?pid={pid}",
        )

    # 3. Blinkit
    if host in _BLINKIT_HOSTS:
        # Path: /prn/{slug}/prid/{id}
        m = re.match(r"^/prn/([^/]+)/prid/([^/?#]+)", path)
        if not m:
            raise ValueError(
                f"Could not extract product path '/prn/{{slug}}/prid/{{id}}' from Blinkit URL: {url}"
            )
        slug, prid = m.group(1), m.group(2)
        return ProductRef(
            platform="blinkit",
            sku=prid,
            url=f"https://blinkit.com/prn/{slug}/prid/{prid}",
        )

    # 4. Zepto
    if host in _ZEPTO_HOSTS:
        # Path: /pn/{slug}/pvid/{uuid}
        m = re.match(r"^/pn/([^/]+)/pvid/([^/?#]+)", path)
        if not m:
            raise ValueError(
                f"Could not extract product path '/pn/{{slug}}/pvid/{{uuid}}' from Zepto URL: {url}"
            )
        slug, pvid = m.group(1), m.group(2)
        return ProductRef(
            platform="zepto",
            sku=pvid,
            url=f"https://www.zeptonow.com/pn/{slug}/pvid/{pvid}",
        )

    # 5. Instamart
    if host in _INSTAMART_HOSTS:
        # Path: /instamart/item/{id}
        m = re.match(r"^/instamart/item/([^/?#]+)", path)
        if not m:
            raise ValueError(
                f"Could not extract product path '/instamart/item/{{id}}' from Swiggy Instamart URL: {url}"
            )
        item_id = m.group(1)
        return ProductRef(
            platform="instamart",
            sku=item_id,
            url=f"https://www.swiggy.com/instamart/item/{item_id}",
        )

    raise ValueError(f"Unsupported host/platform: {host}")
