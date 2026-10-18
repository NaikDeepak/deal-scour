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
    url2 = "https://dl.flipkart.com/amul-butter/p/itm123?pid=PID999"
    ref2 = parse_product_url(url2)
    assert ref2 == ProductRef(
        platform="flipkart",
        sku="PID999",
        url="https://www.flipkart.com/amul-butter/p/itm123?pid=PID999",
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

    url2 = "https://zepto.com/pn/milk/pvid/uuid-1234"
    ref2 = parse_product_url(url2)
    assert ref2 == ProductRef(
        platform="zepto",
        sku="uuid-1234",
        url="https://www.zeptonow.com/pn/milk/pvid/uuid-1234",
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
