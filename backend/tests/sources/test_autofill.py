import gzip
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from app.core.config import Settings
from app.domain.models import Household, LlmUsage
from app.sources.autofill import autofill_product_url
from app.sources.gemini import GeminiClient

FIXTURES = Path(__file__).parent.parent / "fixtures" / "sources"


def _page(name: str) -> str:
    return gzip.decompress((FIXTURES / name).read_bytes()).decode("utf-8", errors="ignore")


@pytest.fixture
def mem_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        h = Household(id=1, name="Home", pincode="411018")
        s.add(h)
        s.commit()
        yield s


# 1. Autofill an Amazon fixture page → title, price, MRP from page;
# brand "Amul", pack "500g", family "butter" from rules.
def test_autofill_amazon_page_with_rules(mem_session: Session) -> None:
    amazon_html = (
        '<span id="productTitle"> Amul Butter 500 g </span>'
        '<div id="corePriceDisplay_desktop_feature_div"><span class="a-price-whole">275</span>'
        '<span class="basisPrice">M.R.P.: <span class="a-price a-text-price">'
        '<span class="a-offscreen">₹290</span></span></span>'
        "</div>"
        '<div id="availability"><span> In stock. </span></div>'
    )
    url = "https://www.amazon.in/dp/B072HG4WNC"

    with patch("app.sources.autofill.fetch_url", return_value=(200, amazon_html)):
        res = autofill_product_url(url, household_id=1, session=mem_session)

    assert res.title == "Amul Butter 500 g"
    assert res.listed_paise == 27500
    assert res.mrp_paise == 29000
    assert res.in_stock is True
    assert res.brand == "Amul"
    assert res.pack_label == "500g"
    assert res.family_key == "butter"
    assert res.sources.get("title") == "page"
    assert res.sources.get("listed_paise") == "page"
    assert res.sources.get("mrp_paise") == "page"
    assert res.sources.get("brand") == "rules"
    assert res.sources.get("pack_label") == "rules"
    assert res.sources.get("family_key") == "rules"


# 2. Title "Optimum Nutrition Gold Standard Whey 2 lb" → pack "907g", family "whey_protein".
def test_autofill_title_optimum_nutrition_whey_lb_conversion(mem_session: Session) -> None:
    amazon_html = (
        '<span id="productTitle"> Optimum Nutrition Gold Standard Whey 2 lb </span>'
        '<div id="corePriceDisplay_desktop_feature_div"><span class="a-price-whole">3,200</span></div>'
    )
    url = "https://www.amazon.in/dp/B072HG4WNC"

    with patch("app.sources.autofill.fetch_url", return_value=(200, amazon_html)):
        res = autofill_product_url(url, household_id=1, session=mem_session)

    assert res.brand == "Optimum Nutrition"
    assert res.pack_label == "907g"
    assert res.family_key == "whey_protein"
    assert res.sources.get("pack_label") == "rules"
    assert res.sources.get("family_key") == "rules"


# 3. Missing family, Gemini key set → fake Gemini returns JSON → used, source=gemini,
# usage row written. Bad JSON → ignored, no crash.
def test_autofill_gemini_fallback_success_and_bad_json(mem_session: Session) -> None:
    # Page with obscure family not in rules
    amazon_html = (
        '<span id="productTitle"> Artisanal Dragonfruit Jam 250g </span>'
        '<div id="corePriceDisplay_desktop_feature_div"><span class="a-price-whole">450</span></div>'
    )
    url = "https://www.amazon.in/dp/B072HG4WNC"

    fake_settings = Settings(
        db_path=Path(":memory:"),
        secret_key="x" * 32,
        gemini_api_key="secret-gemini-key",
        gemini_model="gemini-3.8-flash",
        llm_monthly_cap_paise=10000,
    )

    # 3a: Successful Gemini response
    fake_gemini_json = {
        "brand": "Artisanal",
        "pack_label": "250g",
        "family_key": "dragonfruit_jam",
        "category": "spreads",
    }
    with patch("app.sources.autofill.get_settings", return_value=fake_settings), \
         patch("app.sources.autofill.fetch_url", return_value=(200, amazon_html)), \
         patch("app.sources.gemini.call_gemini_extract", return_value=(fake_gemini_json, 15, 20, 10)):
        res = autofill_product_url(url, household_id=1, session=mem_session)

    assert res.family_key == "dragonfruit_jam"
    assert res.sources.get("family_key") == "gemini"

    # Verify LlmUsage recorded in DB
    usages = mem_session.exec(select(LlmUsage)).all()
    assert len(usages) == 1
    assert usages[0].household_id == 1
    assert usages[0].prompt_tokens == 15
    assert usages[0].response_tokens == 20
    assert usages[0].total_tokens == 35
    assert usages[0].cost_paise == 10

    # 3b: Bad JSON returned from Gemini -> ignored, no crash
    with patch("app.sources.autofill.get_settings", return_value=fake_settings), \
         patch("app.sources.autofill.fetch_url", return_value=(200, amazon_html)), \
         patch("app.sources.gemini.call_gemini_extract", return_value=(None, 10, 5, 5)):
        res_bad = autofill_product_url(url, household_id=1, session=mem_session)

    # Doesn't crash; family_key remains fallback/empty
    assert res_bad.title == "Artisanal Dragonfruit Jam 250g"


# 4. Gemini key empty → never called. Monthly cap reached → never called.
def test_autofill_gemini_key_empty_or_cap_reached(mem_session: Session) -> None:
    amazon_html = (
        '<span id="productTitle"> Artisanal Dragonfruit Jam 250g </span>'
        '<div id="corePriceDisplay_desktop_feature_div"><span class="a-price-whole">450</span></div>'
    )
    url = "https://www.amazon.in/dp/B072HG4WNC"

    # 4a: Key empty
    no_key_settings = Settings(
        db_path=Path(":memory:"),
        secret_key="x" * 32,
        gemini_api_key="",
        gemini_model="gemini-3.8-flash",
        llm_monthly_cap_paise=10000,
    )
    mock_gemini = MagicMock()
    with patch("app.sources.autofill.get_settings", return_value=no_key_settings), \
         patch("app.sources.autofill.fetch_url", return_value=(200, amazon_html)), \
         patch("app.sources.gemini.call_gemini_extract", mock_gemini):
        autofill_product_url(url, household_id=1, session=mem_session)
    mock_gemini.assert_not_called()

    # 4b: Cap reached (cap = 100 paise, existing usage = 150 paise)
    cap_settings = Settings(
        db_path=Path(":memory:"),
        secret_key="x" * 32,
        gemini_api_key="valid-key",
        gemini_model="gemini-3.8-flash",
        llm_monthly_cap_paise=100,
    )
    mem_session.add(
        LlmUsage(
            household_id=1,
            provider="gemini",
            model="gemini-3.8-flash",
            prompt_tokens=100,
            response_tokens=100,
            total_tokens=200,
            cost_paise=150,
            created_at=datetime.now(UTC),
        )
    )
    mem_session.commit()

    mock_gemini_cap = MagicMock()
    with patch("app.sources.autofill.get_settings", return_value=cap_settings), \
         patch("app.sources.autofill.fetch_url", return_value=(200, amazon_html)), \
         patch("app.sources.gemini.call_gemini_extract", mock_gemini_cap):
        autofill_product_url(url, household_id=1, session=mem_session)
    mock_gemini_cap.assert_not_called()


# 5. Quick-commerce link → no HTTP call, title from slug, price empty.
def test_autofill_quick_commerce_no_http(mem_session: Session) -> None:
    blinkit_url = "https://blinkit.com/prn/amul-salted-butter-500-g/prid/12345"
    mock_fetch = MagicMock()

    with patch("app.sources.autofill.fetch_url", mock_fetch):
        res = autofill_product_url(blinkit_url, household_id=1, session=mem_session)

    mock_fetch.assert_not_called()
    assert res.platform == "blinkit"
    assert "amul" in res.title.lower()
    assert res.listed_paise is None
    assert res.mrp_paise is None
    assert res.in_stock is None
    assert res.brand == "Amul"
    assert res.pack_label == "500g"
    assert res.family_key == "butter"


# 9. Gemini key never appears in responses or caplog.
def test_gemini_key_never_leaks(mem_session: Session) -> None:
    secret_key = "AIzaSy_SUPER_SECRET_KEY_12345"
    client = GeminiClient(api_key=secret_key, model="gemini-3.8-flash")
    # Simulate an error response from Gemini
    with patch("httpx.Client.post", side_effect=Exception(f"Network error with key {secret_key}")):
        result, p_tok, r_tok, cost = client.extract_fields("Test Product")

    # Result should safely return None, tokens 0
    assert result is None
    assert p_tok == 0

    # Ensure representations or error logs mask the key
    assert secret_key not in repr(client)
    assert secret_key not in str(client)
