import logging
import re
from datetime import datetime

from pydantic import BaseModel, Field
from sqlmodel import Session

from app.core import clock
from app.core.config import get_settings
from app.core.money import Paise
from app.domain.models import LlmUsage
from app.pricing.fee_schedules import Platform
from app.sources import gemini
from app.sources.fetcher import _RUN_LOCK, fetch_url
from app.sources.pages import parse_amazon_product, parse_flipkart_product
from app.sources.urls import parse_product_url

logger = logging.getLogger(__name__)

KNOWN_BRANDS = [
    "Optimum Nutrition",
    "Mother Dairy",
    "Tata Sampann",
    "MuscleBlaze",
    "Aashirvaad",
    "Britannia",
    "Epigamia",
    "Fortune",
    "Nestlé",
    "Nestle",
    "Pintola",
    "Saffola",
    "Eggoz",
    "Quaker",
    "Amul",
    "Tata",
]

KEYWORD_FAMILY_MAP = [
    ("peanut butter", "peanut_butter", "fitness"),
    ("cheese slices", "cheese_slices", "dairy"),
    ("cheese slice", "cheese_slices", "dairy"),
    ("cheese block", "cheese_block", "dairy"),
    ("whey protein", "whey_protein", "fitness"),
    ("whey", "whey_protein", "fitness"),
    ("butter", "butter", "dairy"),
    ("paneer", "paneer", "dairy"),
    ("ghee", "ghee", "dairy"),
    ("yogurt", "yogurt", "dairy"),
    ("curd", "yogurt", "dairy"),
    ("milk", "milk", "dairy"),
    ("bread", "bread", "bakery"),
    ("eggs", "eggs", "poultry"),
    ("egg", "eggs", "poultry"),
    ("atta", "atta", "staples"),
    ("oil", "oil", "staples"),
    ("dal", "dal", "staples"),
    ("oats", "oats", "staples"),
    ("salt", "salt", "staples"),
]


class AutofillSuggestion(BaseModel):
    url: str
    platform: Platform
    sku: str
    title: str
    brand: str
    pack_label: str
    category: str
    family_key: str
    listed_paise: Paise | None = None
    mrp_paise: Paise | None = None
    in_stock: bool | None = None
    sources: dict[str, str] = Field(default_factory=dict)


def _extract_brand(title: str) -> str:
    for brand in KNOWN_BRANDS:
        pattern = rf"\b{re.escape(brand)}\b"
        if re.search(pattern, title, re.IGNORECASE):
            return brand

    words = re.findall(r"[A-Za-z0-9&]+", title)
    if words:
        return str(words[0]).title()
    return "Generic"


def _extract_pack_label(title: str) -> str | None:
    # Check pounds (lb / lbs) conversion first: 2 lb -> 907g
    lb_m = re.search(r"\b(\d+(?:\.\d+)?)\s*(?:lb|lbs)\b", title, re.IGNORECASE)
    if lb_m:
        val = float(lb_m.group(1))
        grams = round(val * 453.59237)
        return f"{grams}g"

    # Match metric and count units
    m = re.search(
        r"\b(\d+(?:\.\d+)?)\s*(kg|kgs|g|gm|gms|ml|mls|l|ltr|ltrs|pcs|pieces|pc)\b",
        title,
        re.IGNORECASE,
    )
    if m:
        val_str = m.group(1)
        raw_unit = m.group(2).lower()
        if raw_unit in ("kg", "kgs"):
            unit = "kg"
        elif raw_unit in ("g", "gm", "gms"):
            unit = "g"
        elif raw_unit in ("ml", "mls"):
            unit = "ml"
        elif raw_unit in ("l", "ltr", "ltrs"):
            unit = "L"
        else:
            unit = "pcs"
        return f"{val_str}{unit}"
    return None


def _extract_family_and_category(title: str) -> tuple[str | None, str | None]:
    lower_title = title.lower()
    for kw, family, category in KEYWORD_FAMILY_MAP:
        pattern = rf"\b{re.escape(kw)}\b"
        if re.search(pattern, lower_title):
            return family, category
    return None, None


def _slug_to_title(slug: str) -> str:
    cleaned = re.sub(r"[-_]+", " ", slug).strip()
    return " ".join(word.capitalize() for word in cleaned.split())


def autofill_product_url(
    url: str,
    household_id: int,
    session: Session,
    now_dt: datetime | None = None,
) -> AutofillSuggestion:
    ref = parse_product_url(url)
    now = now_dt or clock.now()
    settings = get_settings()

    sources: dict[str, str] = {}
    title = ""
    listed_paise: Paise | None = None
    mrp_paise: Paise | None = None
    in_stock: bool | None = None

    if ref.platform in ("amazon", "flipkart"):
        with _RUN_LOCK:
            status_code, body = fetch_url(ref.url)
        if status_code != 200:
            raise ValueError(f"Failed to fetch {ref.platform} product page (HTTP {status_code})")

        page_res = parse_amazon_product(body) if ref.platform == "amazon" else parse_flipkart_product(body)

        title = (page_res.title or "").strip()
        listed_paise = page_res.listed_paise
        mrp_paise = page_res.mrp_paise if page_res.mrp_paise is not None else page_res.listed_paise
        in_stock = page_res.in_stock

        if title:
            sources["title"] = "page"
        if listed_paise is not None:
            sources["listed_paise"] = "page"
        if mrp_paise is not None:
            sources["mrp_paise"] = "page"
        if in_stock is not None:
            sources["in_stock"] = "page"
    else:
        # Quick-commerce: Blinkit, Zepto, Instamart -> slug only, never fetched
        slug_match = re.search(r"/(?:prn|pn|item)/([^/?#]+)", url)
        raw_slug = slug_match.group(1) if slug_match else ""
        title = _slug_to_title(raw_slug) if raw_slug else f"{ref.platform.title()} item"
        sources["title"] = "slug"

    # Rules-based attribute extraction
    brand = _extract_brand(title)
    sources["brand"] = "rules"

    pack_label = _extract_pack_label(title)
    if pack_label:
        sources["pack_label"] = "rules"

    family_key, category = _extract_family_and_category(title)
    if family_key:
        sources["family_key"] = "rules"
    if category:
        sources["category"] = "rules"

    # Fallback to Gemini if any field is missing, key is set, and under monthly cap
    missing_fields = not all([brand, pack_label, family_key, category])
    if (
        missing_fields
        and settings.gemini_api_key
        and not gemini.is_monthly_cap_reached(session, household_id, settings.llm_monthly_cap_paise, now)
    ):
        gemini_data, p_tok, r_tok, cost = gemini.call_gemini_extract(
            settings.gemini_api_key,
            settings.gemini_model,
            title,
        )
        if p_tok > 0 or r_tok > 0:
            usage = LlmUsage(
                household_id=household_id,
                provider="gemini",
                model=settings.gemini_model,
                prompt_tokens=p_tok,
                response_tokens=r_tok,
                total_tokens=p_tok + r_tok,
                cost_paise=cost,
                created_at=now,
            )
            session.add(usage)
            session.commit()

        if gemini_data:
            if not brand and gemini_data.get("brand"):
                brand = gemini_data["brand"]
                sources["brand"] = "gemini"
            if not pack_label and gemini_data.get("pack_label"):
                pack_label = gemini_data["pack_label"]
                sources["pack_label"] = "gemini"
            if not family_key and gemini_data.get("family_key"):
                family_key = gemini_data["family_key"]
                sources["family_key"] = "gemini"
            if not category and gemini_data.get("category"):
                category = gemini_data["category"]
                sources["category"] = "gemini"

    return AutofillSuggestion(
        url=ref.url,
        platform=ref.platform,
        sku=ref.sku,
        title=title,
        brand=brand or "Generic",
        pack_label=pack_label or "1pc",
        category=category or "staples",
        family_key=family_key or "",
        listed_paise=listed_paise,
        mrp_paise=mrp_paise,
        in_stock=in_stock,
        sources=sources,
    )
