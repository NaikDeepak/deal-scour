import json
import re
from typing import Annotated
from urllib.parse import quote_plus

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlmodel import Session, col, select

from app.core.db import current_household_id, get_session
from app.core.money import Paise
from app.domain.catalog_import import CatalogSuggestion
from app.domain.models import CatalogProduct, CustomListing
from app.pricing.fee_schedules import Platform
from app.pricing.units import parse_pack
from app.sources.autofill import _extract_brand, _extract_pack_label
from app.sources.urls import parse_product_url

router = APIRouter()

HouseholdIdDep = Annotated[int, Depends(current_household_id)]
SessionDep = Annotated[Session, Depends(get_session)]


class CatalogProductOut(BaseModel):
    id: int
    seed_product_id: str
    name: str
    brand: str
    category: str
    family_key: str
    pack_label: str
    target_pack_weight_g: int
    suggestions: list[CatalogSuggestion] = Field(default_factory=list)


class SearchUrlOut(BaseModel):
    platform: Platform
    url: str


class CandidateIn(BaseModel):
    platform: Platform
    url: str
    title: str
    price_paise: Paise | None = None
    pack_label: str | None = None


class CandidatesRequest(BaseModel):
    results: list[CandidateIn] = Field(max_length=25)


class ScoredCandidateOut(BaseModel):
    platform: Platform
    sku: str
    url: str
    title: str
    brand: str
    price_paise: Paise | None = None
    pack_label: str | None = None
    pack_matches: bool
    score: int
    existing_listing_id: str | None = None


def _to_catalog_out(row: CatalogProduct) -> CatalogProductOut:
    assert row.id is not None
    try:
        raw_suggestions = json.loads(row.suggestions_json or "[]")
    except ValueError:
        raw_suggestions = []
    suggestions = [CatalogSuggestion(**s) for s in raw_suggestions if isinstance(s, dict)]
    return CatalogProductOut(
        id=row.id,
        seed_product_id=row.seed_product_id,
        name=row.name,
        brand=row.brand,
        category=row.category,
        family_key=row.family_key,
        pack_label=row.pack_label,
        target_pack_weight_g=row.target_pack_weight_g,
        suggestions=suggestions,
    )


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _get_household_catalog_product(
    session: Session,
    household_id: int,
    catalog_id: int,
) -> CatalogProduct:
    row = session.exec(
        select(CatalogProduct).where(
            CatalogProduct.id == catalog_id,
            CatalogProduct.household_id == household_id,
        )
    ).first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Catalog product not found",
        )
    return row


@router.get("/catalog", response_model=list[CatalogProductOut])
def search_catalog(
    household_id: HouseholdIdDep,
    session: SessionDep,
    q: str = Query(default=""),
    limit: int = Query(default=20, ge=1, le=100),
) -> list[CatalogProductOut]:
    rows = session.exec(
        select(CatalogProduct)
        .where(CatalogProduct.household_id == household_id)
        .order_by(col(CatalogProduct.id).asc())
    ).all()

    q_words = _words(q)
    if not q_words:
        return [_to_catalog_out(r) for r in rows[:limit]]

    matched: list[CatalogProductOut] = []
    for r in rows:
        product_tokens = _words(f"{r.brand} {r.name}")
        if all(any(qw in tok for tok in product_tokens) for qw in q_words):
            matched.append(_to_catalog_out(r))
            if len(matched) >= limit:
                break
    return matched


def _build_search_urls(query_str: str) -> list[SearchUrlOut]:
    encoded = quote_plus(query_str.strip())
    return [
        SearchUrlOut(platform="amazon", url=f"https://www.amazon.in/s?k={encoded}"),
        SearchUrlOut(platform="flipkart", url=f"https://www.flipkart.com/search?q={encoded}"),
        SearchUrlOut(platform="blinkit", url=f"https://blinkit.com/s/?q={encoded}"),
        SearchUrlOut(platform="zepto", url=f"https://www.zepto.com/search?query={encoded}"),
        SearchUrlOut(
            platform="instamart",
            url=f"https://www.swiggy.com/instamart/search?query={encoded}",
        ),
    ]


def _resolve_candidate_brand(candidate_title: str, catalog_brand: str | None) -> str:
    if catalog_brand and catalog_brand.strip():
        b = catalog_brand.strip()
        pattern = rf"\b{re.escape(b)}\b"
        if re.search(pattern, candidate_title, re.IGNORECASE):
            return b
    return _extract_brand(candidate_title)


def _check_pack_matches(pack_label: str | None, target_weight_g: int) -> bool:
    if not pack_label or target_weight_g <= 0:
        return False
    try:
        parsed = parse_pack(pack_label)
    except ValueError:
        return False
    if parsed.unit not in ("g", "ml"):
        return False
    return abs(parsed.qty - target_weight_g) * 10 <= target_weight_g


@router.get("/catalog/search-urls", response_model=list[SearchUrlOut])
def get_free_text_search_urls(
    household_id: HouseholdIdDep,
    q: str = Query(..., min_length=1, max_length=80),
) -> list[SearchUrlOut]:
    return _build_search_urls(q)


@router.get("/catalog/{id}/search-urls", response_model=list[SearchUrlOut])
def get_catalog_search_urls(
    id: int,
    household_id: HouseholdIdDep,
    session: SessionDep,
) -> list[SearchUrlOut]:
    row = _get_household_catalog_product(session, household_id, id)

    name_clean = row.name.strip()
    brand_clean = row.brand.strip()
    if name_clean.lower().startswith(brand_clean.lower()):
        query_str = f"{name_clean} {row.pack_label}".strip()
    else:
        query_str = f"{brand_clean} {name_clean} {row.pack_label}".strip()

    return _build_search_urls(query_str)


@router.post("/catalog/candidates", response_model=list[ScoredCandidateOut])
def score_free_text_candidates(
    req: CandidatesRequest,
    household_id: HouseholdIdDep,
    session: SessionDep,
    q: str = Query(..., min_length=1, max_length=80),
    pack: str | None = Query(default=None, max_length=20),
) -> list[ScoredCandidateOut]:
    target_weight_g = 0
    if pack:
        try:
            parsed = parse_pack(pack)
            if parsed.unit in ("g", "ml"):
                target_weight_g = parsed.qty
        except ValueError:
            target_weight_g = 0

    q_words = list(dict.fromkeys(_words(q)))
    query_brand = _extract_brand(q)
    brand_words = list(dict.fromkeys(_words(query_brand))) if query_brand != "Generic" else []

    existing_listings = session.exec(
        select(CustomListing).where(
            CustomListing.household_id == household_id,
            col(CustomListing.archived).is_(False),
        )
    ).all()
    existing_by_key = {(c.platform, c.sku): c.listing_id for c in existing_listings}
    existing_by_url = {c.url: c.listing_id for c in existing_listings}

    scored: list[ScoredCandidateOut] = []
    for item in req.results:
        try:
            ref = parse_product_url(item.url)
        except ValueError:
            continue

        title_clean = item.title.strip()
        title_words = set(_words(title_clean))

        raw_pack = item.pack_label
        pack_label = (raw_pack and _extract_pack_label(raw_pack)) or _extract_pack_label(title_clean)
        pack_matches = _check_pack_matches(pack_label, target_weight_g) if target_weight_g > 0 else False

        catalog_brand_hint = query_brand if query_brand != "Generic" else None
        candidate_brand = _resolve_candidate_brand(title_clean, catalog_brand_hint)

        score = 0
        if brand_words and any(bw in title_words for bw in brand_words):
            score += 2
        if pack_matches:
            score += 2
        for nw in q_words:
            if nw in title_words:
                score += 1

        existing_id = existing_by_url.get(ref.url) or existing_by_key.get((ref.platform, ref.sku))

        scored.append(
            ScoredCandidateOut(
                platform=ref.platform,
                sku=ref.sku,
                url=ref.url,
                title=title_clean,
                brand=candidate_brand,
                price_paise=item.price_paise,
                pack_label=pack_label,
                pack_matches=pack_matches,
                score=score,
                existing_listing_id=existing_id,
            )
        )

    scored.sort(key=lambda c: c.score, reverse=True)
    return scored


@router.post("/catalog/{id}/candidates", response_model=list[ScoredCandidateOut])
def score_catalog_candidates(
    id: int,
    req: CandidatesRequest,
    household_id: HouseholdIdDep,
    session: SessionDep,
) -> list[ScoredCandidateOut]:
    row = _get_household_catalog_product(session, household_id, id)

    brand_words = list(dict.fromkeys(_words(row.brand)))
    name_words = list(dict.fromkeys(_words(row.name)))

    existing_listings = session.exec(
        select(CustomListing).where(
            CustomListing.household_id == household_id,
            col(CustomListing.archived).is_(False),
        )
    ).all()
    existing_by_key = {(c.platform, c.sku): c.listing_id for c in existing_listings}
    existing_by_url = {c.url: c.listing_id for c in existing_listings}

    scored: list[ScoredCandidateOut] = []
    for item in req.results:
        try:
            ref = parse_product_url(item.url)
        except ValueError:
            continue

        title_clean = item.title.strip()
        title_words = set(_words(title_clean))

        raw_pack = item.pack_label
        pack_label = (raw_pack and _extract_pack_label(raw_pack)) or _extract_pack_label(title_clean)
        pack_matches = _check_pack_matches(pack_label, row.target_pack_weight_g)

        candidate_brand = _resolve_candidate_brand(title_clean, row.brand)

        score = 0
        if brand_words and any(bw in title_words for bw in brand_words):
            score += 2
        if pack_matches:
            score += 2
        for nw in name_words:
            if nw in title_words:
                score += 1

        existing_id = existing_by_url.get(ref.url) or existing_by_key.get((ref.platform, ref.sku))

        scored.append(
            ScoredCandidateOut(
                platform=ref.platform,
                sku=ref.sku,
                url=ref.url,
                title=title_clean,
                brand=candidate_brand,
                price_paise=item.price_paise,
                pack_label=pack_label,
                pack_matches=pack_matches,
                score=score,
                existing_listing_id=existing_id,
            )
        )

    scored.sort(key=lambda c: c.score, reverse=True)
    return scored
