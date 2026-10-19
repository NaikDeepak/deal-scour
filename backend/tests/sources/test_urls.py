import pytest

from app.sources.urls import ProductRef, parse_product_url


def test_amazon_url_parsing() -> None:
    # Slug with dp and query params
    url1 = "https://www.amazon.in/Amul-Butter-500g/dp/B00ZXUW9ZK/ref=sr_1_1?keywords=amul+butter"
    ref1 = parse_product_url(url1)
    assert ref1 == ProductRef(
        platform="amazon",
        sku="B00ZXUW9ZK",
        url="https://www.amazon.in/dp/B00ZXUW9ZK",
    )

    # Bare dp
    url2 = "https://amazon.in/dp/B00ZXUW9ZK"
    ref2 = parse_product_url(url2)
    assert ref2 == ProductRef(
        platform="amazon",
        sku="B00ZXUW9ZK",
        url="https://www.amazon.in/dp/B00ZXUW9ZK",
    )

    # m.amazon.in with gp/product
    url3 = "https://m.amazon.in/gp/product/B00ZXUW9ZK?tag=deals"
    ref3 = parse_product_url(url3)
    assert ref3 == ProductRef(
        platform="amazon",
        sku="B00ZXUW9ZK",
        url="https://www.amazon.in/dp/B00ZXUW9ZK",
    )

    # gp/aw/d
    url4 = "https://www.amazon.in/gp/aw/d/B00ZXUW9ZK"
    ref4 = parse_product_url(url4)
    assert ref4 == ProductRef(
        platform="amazon",
        sku="B00ZXUW9ZK",
        url="https://www.amazon.in/dp/B00ZXUW9ZK",
    )


def test_flipkart_url_parsing() -> None:
    url = "https://www.flipkart.com/amul-butter-500g/p/itmf12345?pid=BUT1234567890&lid=LST123&marketplace=FLIPKART"
    ref = parse_product_url(url)
    assert ref == ProductRef(
        platform="flipkart",
        sku="BUT1234567890",
        url="https://www.flipkart.com/amul-butter-500g/p/itmf12345?pid=BUT1234567890",
    )

    # dl.flipkart.com full link
    url2 = "https://dl.flipkart.com/amul-butter/p/itm123456?pid=PID12345678"
    ref2 = parse_product_url(url2)
    assert ref2 == ProductRef(
        platform="flipkart",
        sku="PID12345678",
        url="https://www.flipkart.com/amul-butter/p/itm123456?pid=PID12345678",
    )


def test_flipkart_missing_pid_raises() -> None:
    url = "https://www.flipkart.com/amul-butter-500g/p/itmf12345?lid=LST123"
    with pytest.raises(ValueError, match="pid"):
        parse_product_url(url)


def test_blinkit_url_parsing() -> None:
    url = "https://blinkit.com/prn/amul-pasteurised-butter/prid/12345?utm_source=share"
    ref = parse_product_url(url)
    assert ref == ProductRef(
        platform="blinkit",
        sku="12345",
        url="https://blinkit.com/prn/amul-pasteurised-butter/prid/12345",
    )


def test_zepto_url_parsing() -> None:
    url = "https://www.zeptonow.com/pn/amul-butter/pvid/f81d4fae-7dec-11d0-a765-00a0c91e6bf6?ref=home"
    ref = parse_product_url(url)
    assert ref == ProductRef(
        platform="zepto",
        sku="f81d4fae-7dec-11d0-a765-00a0c91e6bf6",
        url="https://www.zeptonow.com/pn/amul-butter/pvid/f81d4fae-7dec-11d0-a765-00a0c91e6bf6",
    )

    url2 = "https://zepto.com/pn/milk/pvid/a1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c6d"
    ref2 = parse_product_url(url2)
    assert ref2 == ProductRef(
        platform="zepto",
        sku="a1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c6d",
        url="https://www.zeptonow.com/pn/milk/pvid/a1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c6d",
    )


def test_instamart_url_parsing() -> None:
    url = "https://www.swiggy.com/instamart/item/ITEM12345?search_query=butter"
    ref = parse_product_url(url)
    assert ref == ProductRef(
        platform="instamart",
        sku="ITEM12345",
        url="https://www.swiggy.com/instamart/item/ITEM12345",
    )

    url2 = "https://swiggy.com/instamart/item/ITEM999"
    ref2 = parse_product_url(url2)
    assert ref2 == ProductRef(
        platform="instamart",
        sku="ITEM999",
        url="https://www.swiggy.com/instamart/item/ITEM999",
    )

    # New instamart.in product URL format: /p/<slug>-<ID>
    url3 = (
        "https://instamart.in/p/"
        "tata-sampann-pure-cashews-whole-kaju-nutritious-delicious-T6LJGMXRBD"
    )
    ref3 = parse_product_url(url3)
    assert ref3 == ProductRef(
        platform="instamart",
        sku="T6LJGMXRBD",
        url="https://instamart.in/p/tata-sampann-pure-cashews-whole-kaju-nutritious-delicious-T6LJGMXRBD",
    )

    url4 = (
        "https://www.instamart.in/p/"
        "tata-sampann-pure-cashews-whole-kaju-nutritious-delicious-T6LJGMXRBD/?utm_source=share"
    )
    ref4 = parse_product_url(url4)
    assert ref4 == ProductRef(
        platform="instamart",
        sku="T6LJGMXRBD",
        url="https://instamart.in/p/tata-sampann-pure-cashews-whole-kaju-nutritious-delicious-T6LJGMXRBD",
    )

    # Reject instamart.in search or malformed paths
    with pytest.raises(ValueError):
        parse_product_url("https://instamart.in/search?query=cashews")
    with pytest.raises(ValueError):
        parse_product_url("https://instamart.in/p/shortid-ABC12")



@pytest.mark.parametrize(
    "short_url",
    [
        "https://amzn.in/d/abcd123",
        "https://amzn.to/3xyz",
        "https://fkrt.it/xyz",
        "https://dl.flipkart.com/s/xyz123",
    ],
)
def test_short_links_raise_specific_error(short_url: str) -> None:
    exact_msg = (
        "Short links can't be read without opening them. "
        "Open the link in your browser and paste the full address."
    )
    with pytest.raises(ValueError, match=exact_msg):
        parse_product_url(short_url)


def test_http_raises_error() -> None:
    with pytest.raises(ValueError, match="https"):
        parse_product_url("http://www.amazon.in/dp/B00ZXUW9ZK")


def test_unsupported_host_raises_error() -> None:
    with pytest.raises(ValueError, match="bigbasket"):
        parse_product_url("https://www.bigbasket.com/pd/1/")


def test_review_item_10_anchored_path_patterns() -> None:
    # Trailing segments must be rejected
    with pytest.raises(ValueError):
        parse_product_url("https://www.flipkart.com/amul-butter-500g/p/itmf12345/extra?pid=BUT12345678")

    with pytest.raises(ValueError):
        parse_product_url("https://blinkit.com/prn/amul-butter/prid/12345/extra")

    with pytest.raises(ValueError):
        parse_product_url(
            "https://www.zeptonow.com/pn/amul-butter/pvid/f81d4fae-7dec-11d0-a765-00a0c91e6bf6/extra"
        )

    with pytest.raises(ValueError):
        parse_product_url("https://www.swiggy.com/instamart/item/ITEM12345/extra")

    # Single trailing slash must be accepted
    fk = parse_product_url(
        "https://www.flipkart.com/amul-butter-500g/p/itmf12345/?pid=BUT12345678"
    )
    assert fk.sku == "BUT12345678"

    bl = parse_product_url("https://blinkit.com/prn/amul-butter/prid/12345/")
    assert bl.sku == "12345"

    zp = parse_product_url(
        "https://www.zeptonow.com/pn/amul-butter/pvid/f81d4fae-7dec-11d0-a765-00a0c91e6bf6/"
    )
    assert zp.sku == "f81d4fae-7dec-11d0-a765-00a0c91e6bf6"

    im = parse_product_url("https://www.swiggy.com/instamart/item/ITEM12345/")
    assert im.sku == "ITEM12345"


def test_review_item_11_strict_charset_validation() -> None:
    # Invalid ASIN (contains non-alphanumeric)
    with pytest.raises(ValueError):
        parse_product_url("https://www.amazon.in/dp/B00ZXUW9Z!")

    # Invalid Flipkart pid (query injection)
    with pytest.raises(ValueError):
        parse_product_url(
            "https://www.flipkart.com/amul-butter-500g/p/itmf12345?pid=PID12345%26x%3D1"
        )

    # Invalid Flipkart itm (does not match itm[a-z0-9]{6,20})
    with pytest.raises(ValueError):
        parse_product_url(
            "https://www.flipkart.com/amul-butter-500g/p/baditm?pid=BUT12345678"
        )

    # Invalid Blinkit prid (non-digit)
    with pytest.raises(ValueError):
        parse_product_url("https://blinkit.com/prn/amul-butter/prid/abc123")

    # Invalid Zepto pvid (not a valid UUID)
    with pytest.raises(ValueError):
        parse_product_url("https://www.zeptonow.com/pn/amul-butter/pvid/not-a-uuid-string")

    # Invalid Instamart item id (special characters)
    with pytest.raises(ValueError):
        parse_product_url("https://www.swiggy.com/instamart/item/ITEM$123")

    # Invalid slug (special characters)
    with pytest.raises(ValueError):
        parse_product_url("https://blinkit.com/prn/amul_butter!/prid/12345")


def test_review_item_12_reject_www_blinkit() -> None:
    with pytest.raises(ValueError, match="blinkit"):
        parse_product_url("https://www.blinkit.com/prn/amul-butter/prid/12345")

