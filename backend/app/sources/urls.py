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
_BLINKIT_HOSTS: set[str] = {"blinkit.com"}
_ZEPTO_HOSTS: set[str] = {"zeptonow.com", "www.zeptonow.com", "zepto.com", "www.zepto.com"}
_INSTAMART_HOSTS: set[str] = {"swiggy.com", "www.swiggy.com"}
_INSTAMART_NEW_HOSTS: set[str] = {"instamart.in", "www.instamart.in"}

_RE_SLUG = re.compile(r"^[a-z0-9-]{1,120}$")
_RE_AMAZON_ASIN = re.compile(r"^[A-Z0-9]{10}$")
_RE_FLIPKART_PID = re.compile(r"^[A-Z0-9]{8,24}$")
_RE_FLIPKART_ITM = re.compile(r"^itm[a-z0-9]{6,20}$")
_RE_BLINKIT_PRID = re.compile(r"^[0-9]{1,12}$")
_RE_ZEPTO_PVID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
_RE_INSTAMART_ID = re.compile(r"^[A-Za-z0-9]{1,32}$")
_RE_INSTAMART_NEW_ID = re.compile(r"^[A-Z0-9]{8,32}$")


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
            r"^(?:/[^/]+)?/dp/([A-Za-z0-9]{10})(?:/ref=.*)?/?$|"
            r"^/gp/product/([A-Za-z0-9]{10})(?:/.*)?/?$|"
            r"^/gp/aw/d/([A-Za-z0-9]{10})(?:/.*)?/?$",
            path,
        )
        if not m:
            raise ValueError(f"Could not extract a valid 10-character Amazon ASIN from URL: {url}")
        asin = (m.group(1) or m.group(2) or m.group(3)).upper()
        if not _RE_AMAZON_ASIN.fullmatch(asin):
            raise ValueError(f"Invalid Amazon ASIN: '{asin}'")
        return ProductRef(
            platform="amazon",
            sku=asin,
            url=f"https://www.amazon.in/dp/{asin}",
        )

    # 2. Flipkart
    if host in _FLIPKART_HOSTS:
        # Path: /{slug}/p/{itm} exactly, trailing slash OK
        m = re.match(r"^/([^/]+)/p/([^/?#]+)/?$", path)
        if not m:
            raise ValueError(
                f"Could not extract product path '/{{slug}}/p/{{itm}}' from Flipkart URL: {url}"
            )
        raw_slug, raw_itm = m.group(1), m.group(2)
        slug = raw_slug.lower()
        itm = raw_itm.lower()
        if not _RE_SLUG.fullmatch(slug):
            raise ValueError(f"Invalid Flipkart slug: '{raw_slug}'")
        if not _RE_FLIPKART_ITM.fullmatch(itm):
            raise ValueError(f"Invalid Flipkart item id: '{raw_itm}'")

        qs = parse_qs(parsed.query)
        pids = qs.get("pid")
        if not pids or not pids[0]:
            raise ValueError(f"Flipkart URL is missing required 'pid' parameter: {url}")
        pid = pids[0].upper()
        if not _RE_FLIPKART_PID.fullmatch(pid):
            raise ValueError(f"Invalid Flipkart pid: '{pids[0]}'")

        return ProductRef(
            platform="flipkart",
            sku=pid,
            url=f"https://www.flipkart.com/{slug}/p/{itm}?pid={pid}",
        )

    # 3. Blinkit
    if host in _BLINKIT_HOSTS:
        # Path: /prn/{slug}/prid/{id} exactly, trailing slash OK
        m = re.match(r"^/prn/([^/]+)/prid/([^/?#]+)/?$", path)
        if not m:
            raise ValueError(
                f"Could not extract product path '/prn/{{slug}}/prid/{{id}}' from Blinkit URL: {url}"
            )
        raw_slug, prid = m.group(1), m.group(2)
        slug = raw_slug.lower()
        if not _RE_SLUG.fullmatch(slug):
            raise ValueError(f"Invalid Blinkit slug: '{raw_slug}'")
        if not _RE_BLINKIT_PRID.fullmatch(prid):
            raise ValueError(f"Invalid Blinkit prid: '{prid}'")

        return ProductRef(
            platform="blinkit",
            sku=prid,
            url=f"https://blinkit.com/prn/{slug}/prid/{prid}",
        )

    # 4. Zepto
    if host in _ZEPTO_HOSTS:
        # Path: /pn/{slug}/pvid/{uuid} exactly, trailing slash OK
        m = re.match(r"^/pn/([^/]+)/pvid/([^/?#]+)/?$", path)
        if not m:
            raise ValueError(
                f"Could not extract product path '/pn/{{slug}}/pvid/{{uuid}}' from Zepto URL: {url}"
            )
        raw_slug, raw_pvid = m.group(1), m.group(2)
        slug = raw_slug.lower()
        pvid = raw_pvid.lower()
        if not _RE_SLUG.fullmatch(slug):
            raise ValueError(f"Invalid Zepto slug: '{raw_slug}'")
        if not _RE_ZEPTO_PVID.fullmatch(pvid):
            raise ValueError(f"Invalid Zepto pvid UUID: '{raw_pvid}'")

        return ProductRef(
            platform="zepto",
            sku=pvid,
            url=f"https://www.zeptonow.com/pn/{slug}/pvid/{pvid}",
        )

    # 5a. Instamart (Swiggy domain)
    if host in _INSTAMART_HOSTS:
        # Path: /instamart/item/{id} exactly, trailing slash OK
        m = re.match(r"^/instamart/item/([^/?#]+)/?$", path)
        if not m:
            raise ValueError(
                f"Could not extract product path '/instamart/item/{{id}}' from Swiggy Instamart URL: {url}"
            )
        item_id = m.group(1)
        if not _RE_INSTAMART_ID.fullmatch(item_id):
            raise ValueError(f"Invalid Instamart item id: '{item_id}'")

        return ProductRef(
            platform="instamart",
            sku=item_id,
            url=f"https://www.swiggy.com/instamart/item/{item_id}",
        )

    # 5b. Instamart (instamart.in/p/<slug>-<ID>)
    if host in _INSTAMART_NEW_HOSTS:
        m = re.match(r"^/p/([a-z0-9-]{1,120})-([A-Z0-9]{8,32})/?$", path)
        if not m:
            raise ValueError(
                f"Could not extract product path '/p/{{slug}}-{{ID}}' from Instamart URL: {url}"
            )
        slug, item_id = m.group(1), m.group(2)
        if not _RE_SLUG.fullmatch(slug):
            raise ValueError(f"Invalid Instamart slug: '{slug}'")
        if not _RE_INSTAMART_NEW_ID.fullmatch(item_id):
            raise ValueError(f"Invalid Instamart item id: '{item_id}'")

        return ProductRef(
            platform="instamart",
            sku=item_id,
            url=f"https://instamart.in/p/{slug}-{item_id}",
        )

    raise ValueError(f"Unsupported host/platform: {host}")

