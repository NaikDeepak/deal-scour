import gzip
from pathlib import Path

import pytest

from app.sources.pages import PageBlockedError, PageParseError, parse_amazon_product, parse_flipkart_product

FIXTURES = Path(__file__).parent.parent / "fixtures" / "sources"


def _page(name: str) -> str:
    return gzip.decompress((FIXTURES / name).read_bytes()).decode("utf-8", errors="ignore")


def test_amazon_real_product_page() -> None:
    r = parse_amazon_product(_page("amazon_dp_B072HG4WNC.html.gz"))
    assert r.listed_paise == 180000
    assert r.in_stock is True
    assert r.mrp_paise is None  # sells at MRP: no struck-through price on this page
    assert r.title is not None and r.title.startswith("Ishavasyam Vedic A2 Ghee - 500ml")


def test_flipkart_real_product_page() -> None:
    r = parse_flipkart_product(_page("flipkart_p_JASHRN6FZUFHMESG.html.gz"))
    assert r.listed_paise == 24000
    assert r.mrp_paise == 34900
    assert r.in_stock is True
    assert r.title is not None and r.title.startswith("AQ FITNESS Peanut Butter Whey Protein")


def test_amazon_captcha_is_blocked_not_parsed() -> None:
    page = "<form action='/errors/validateCaptcha'>Type the characters you see in this image</form>"
    with pytest.raises(PageBlockedError):
        parse_amazon_product(page)


def test_flipkart_access_denied_is_blocked() -> None:
    with pytest.raises(PageBlockedError):
        parse_flipkart_product("<html><head><title>Access Denied</title></head></html>")


def test_amazon_struck_mrp_and_out_of_stock() -> None:
    page = (
        '<span id="productTitle"> Amul Butter 500 g </span>'
        '<div id="corePriceDisplay_desktop_feature_div"><span class="a-price-whole">275</span>'
        '<span class="basisPrice">M.R.P.: <span class="a-price a-text-price">'
        '<span class="a-offscreen">₹290</span></span></span>'
        "</div>"
        '<div id="availability"><span> Currently unavailable. </span></div>'
    )
    r = parse_amazon_product(page)
    assert (r.listed_paise, r.mrp_paise, r.in_stock, r.title) == (27500, 29000, False, "Amul Butter 500 g")


def test_amazon_no_price_raises_parse_error() -> None:
    with pytest.raises(PageParseError):
        parse_amazon_product('<span id="productTitle">x</span><div id="availability">In stock</div>')


def test_flipkart_out_of_stock_and_mrp_below_price_ignored() -> None:
    page = (
        '<script type="application/ld+json">[{"@type":"Product","name":"Amul Cheese Slices 200g",'
        '"offers":{"@type":"Offer","price":135,"availability":"https://schema.org/OutOfStock"}}]</script>'
        '<script>{"mrp":99}</script>'
    )
    r = parse_flipkart_product(page)
    assert (r.listed_paise, r.mrp_paise, r.in_stock) == (13500, None, False)


def test_flipkart_without_product_data_raises() -> None:
    with pytest.raises(PageParseError):
        parse_flipkart_product("<script type='application/ld+json'>{\"@type\":\"WebSite\"}</script>")
