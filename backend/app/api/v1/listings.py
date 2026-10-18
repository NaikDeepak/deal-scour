import re
import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlmodel import Session, col, select

from app.core import clock
from app.core.db import current_household_id, get_session
from app.core.money import Paise
from app.domain.catalog import all_listings, compute_freshness, load_seed
from app.domain.models import CustomListing, PriceObservation
from app.pricing.fee_schedules import Platform
from app.pricing.units import parse_pack
from app.sources.urls import parse_product_url

router = APIRouter()

HouseholdIdDep = Annotated[int, Depends(current_household_id)]
SessionDep = Annotated[Session, Depends(get_session)]
ClockDep = Annotated[datetime, Depends(clock.now)]


class ParseListingRequest(BaseModel):
    url: str


class ParseListingResponse(BaseModel):
    platform: Platform
    sku: str
    url: str


class CreateListingRequest(BaseModel):
    url: str
    title: str = Field(min_length=1, max_length=120)
    brand: str = Field(min_length=1, max_length=40)
    pack_label: str
    category: str = Field(min_length=1, max_length=30)
    family_key: str = Field(min_length=1, max_length=40)
    listed_paise: Paise
    mrp_paise: Paise
    member_price_paise: Paise | None = None
    in_stock: bool = True
    icon: str = "🛒"


class CustomListingOut(BaseModel):
    id: int
    household_id: int
    listing_id: str
    platform: Platform
    sku: str
    url: str
    title: str
    brand: str
    pack_label: str
    category: str
    product_key: str
    family_key: str
    icon: str
    archived: bool
    created_at: datetime
    listed_paise: Paise | None = None
    mrp_paise: Paise | None = None
    member_price_paise: Paise | None = None
    in_stock: bool | None = None
    observed_at: datetime | None = None
    freshness: str | None = None
    source: str | None = None


class UpdateListingRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    brand: str | None = Field(default=None, min_length=1, max_length=40)
    pack_label: str | None = None
    category: str | None = Field(default=None, min_length=1, max_length=30)
    family_key: str | None = Field(default=None, min_length=1, max_length=40)
    icon: str | None = None
    archived: bool | None = None


class FamilyOut(BaseModel):
    family_key: str
    count: int
    units: list[str]


def _make_base_slug(brand: str, title: str, pack_label: str) -> str:
    brand_slug = re.sub(r"[^a-z0-9]+", "_", brand.lower()).strip("_")
    pack_slug = re.sub(r"[^a-z0-9]+", "_", pack_label.lower()).strip("_")

    t_words = re.findall(r"[a-z0-9]+", title.lower())
    b_words = re.findall(r"[a-z0-9]+", brand.lower())
    p_words = re.findall(r"[a-z0-9]+", pack_label.lower())

    while t_words and b_words and t_words[:len(b_words)] == b_words:
        t_words = t_words[len(b_words):]
    while t_words and p_words and t_words[-len(p_words):] == p_words:
        t_words = t_words[:-len(p_words)]

    title_slug = "_".join(t_words)
    parts = [p for p in (brand_slug, title_slug, pack_slug) if p]
    candidate = "_".join(parts)
    candidate = re.sub(r"[^a-z0-9_]+", "_", candidate).strip("_")
    return candidate or "product"


@router.post("/listings/parse", response_model=ParseListingResponse)
def parse_listing(req: ParseListingRequest) -> ParseListingResponse:
    try:
        ref = parse_product_url(req.url)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)) from e

    return ParseListingResponse(
        platform=ref.platform,
        sku=ref.sku,
        url=ref.url,
    )


@router.post("/listings", response_model=CustomListingOut, status_code=status.HTTP_201_CREATED)
def create_listing(
    req: CreateListingRequest,
    household_id: HouseholdIdDep,
    session: SessionDep,
    now_dt: ClockDep,
) -> CustomListingOut:
    # 1. URL parsing & canonicalization
    try:
        ref = parse_product_url(req.url)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    # 2. Pack label validation
    try:
        parse_pack(req.pack_label)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=f"Invalid pack_label: {req.pack_label}") from e

    # 3. Category & family_key validation (lowercase slug)
    category_slug = req.category.strip().lower()
    if not re.fullmatch(r"[a-z0-9_]{1,30}", category_slug):
        raise HTTPException(
            status_code=422,
            detail="Category must be a lowercase slug [a-z0-9_] between 1 and 30 characters",
        )

    family_slug = req.family_key.strip().lower()
    if not re.fullmatch(r"[a-z0-9_]{1,40}", family_slug):
        raise HTTPException(
            status_code=422,
            detail="Family key must be a lowercase slug [a-z0-9_] between 1 and 40 characters",
        )

    # 4. Price validations (same as POST /prices)
    if req.listed_paise <= 0:
        raise HTTPException(status_code=422, detail=f"listed_paise must be positive, got {req.listed_paise}")
    if req.mrp_paise < req.listed_paise:
        raise HTTPException(
            status_code=422,
            detail=f"mrp_paise ({req.mrp_paise}) cannot be less than listed_paise ({req.listed_paise})",
        )
    if req.member_price_paise is not None:
        if req.member_price_paise < 0:
            raise HTTPException(status_code=422, detail="member_price_paise cannot be negative")
        if req.member_price_paise > req.listed_paise:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"member_price_paise ({req.member_price_paise}) "
                    f"cannot exceed listed_paise ({req.listed_paise})"
                ),
            )

    # 5. Duplicate (platform, sku) among non-archived for this household
    existing = session.exec(
        select(CustomListing).where(
            CustomListing.household_id == household_id,
            CustomListing.platform == ref.platform,
            CustomListing.sku == ref.sku,
            CustomListing.archived.is_(False),  # type: ignore[attr-defined]
        )
    ).first()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Listing for {ref.platform} with sku '{ref.sku}' already exists in this household",
        )

    # 6. Product key generation
    existing_items = all_listings(session=session, household_id=household_id)
    existing_keys = {item.product_key for item in existing_items}
    base_slug = _make_base_slug(req.brand, req.title, req.pack_label)

    if base_slug not in existing_keys and len(base_slug) <= 60:
        product_key = base_slug
    else:
        i = 2
        candidate = base_slug
        while True:
            suffix = f"_{i}"
            max_len = 60 - len(suffix)
            candidate = f"{base_slug[:max_len].rstrip('_')}{suffix}"
            if candidate not in existing_keys:
                product_key = candidate
                break
            i += 1

    # 7. Insert CustomListing
    temp_id = f"pending-{uuid.uuid4().hex}"
    listing = CustomListing(
        household_id=household_id,
        listing_id=temp_id,
        platform=ref.platform,
        sku=ref.sku,
        url=ref.url,
        title=req.title,
        brand=req.brand,
        pack_label=req.pack_label,
        category=category_slug,
        product_key=product_key,
        family_key=family_slug,
        icon=req.icon or "🛒",
        archived=False,
        created_at=now_dt,
    )
    session.add(listing)
    session.flush()

    listing.listing_id = f"cus-{listing.id}"
    session.add(listing)

    # 8. Create first price_observation
    obs = PriceObservation(
        household_id=household_id,
        listing_id=listing.listing_id,
        listed_paise=req.listed_paise,
        mrp_paise=req.mrp_paise,
        member_price_paise=req.member_price_paise,
        in_stock=req.in_stock,
        eta_minutes=None,
        source="manual",
        note=None,
        observed_at=now_dt,
    )
    session.add(obs)
    session.commit()
    session.refresh(listing)

    freshness = compute_freshness(listing.platform, obs.observed_at, now_dt)

    assert listing.id is not None
    return CustomListingOut(
        id=listing.id,
        household_id=listing.household_id,
        listing_id=listing.listing_id,
        platform=ref.platform,
        sku=listing.sku,
        url=listing.url,
        title=listing.title,
        brand=listing.brand,
        pack_label=listing.pack_label,
        category=listing.category,
        product_key=listing.product_key,
        family_key=listing.family_key,
        icon=listing.icon,
        archived=listing.archived,
        created_at=listing.created_at,
        listed_paise=obs.listed_paise,
        mrp_paise=obs.mrp_paise,
        member_price_paise=obs.member_price_paise,
        in_stock=obs.in_stock,
        observed_at=obs.observed_at,
        freshness=freshness,
        source="manual",
    )


@router.get("/listings", response_model=list[CustomListingOut])
def get_listings(
    household_id: HouseholdIdDep,
    session: SessionDep,
    now_dt: ClockDep,
    include_archived: bool = Query(False),
) -> list[CustomListingOut]:
    stmt = select(CustomListing).where(CustomListing.household_id == household_id)
    if not include_archived:
        stmt = stmt.where(CustomListing.archived.is_(False))  # type: ignore[attr-defined]
    stmt = stmt.order_by(col(CustomListing.id).asc())
    listings = session.exec(stmt).all()

    obs_stmt = (
        select(PriceObservation)
        .where(PriceObservation.household_id == household_id)
        .order_by(col(PriceObservation.observed_at).asc(), col(PriceObservation.id).asc())
    )
    observations = session.exec(obs_stmt).all()
    latest_by_listing: dict[str, PriceObservation] = {}
    for o in observations:
        prev = latest_by_listing.get(o.listing_id)
        if prev is None:
            latest_by_listing[o.listing_id] = o
        else:
            prev_key = (prev.observed_at, prev.id or 0)
            curr_key = (o.observed_at, o.id or 0)
            if curr_key >= prev_key:
                latest_by_listing[o.listing_id] = o

    result: list[CustomListingOut] = []
    for item in listings:
        obs = latest_by_listing.get(item.listing_id)
        freshness = compute_freshness(item.platform, obs.observed_at, now_dt) if obs else None
        assert item.id is not None
        result.append(
            CustomListingOut(
                id=item.id,
                household_id=item.household_id,
                listing_id=item.listing_id,
                platform=item.platform,  # type: ignore[arg-type]
                sku=item.sku,
                url=item.url,
                title=item.title,
                brand=item.brand,
                pack_label=item.pack_label,
                category=item.category,
                product_key=item.product_key,
                family_key=item.family_key,
                icon=item.icon,
                archived=item.archived,
                created_at=item.created_at,
                listed_paise=obs.listed_paise if obs else None,
                mrp_paise=obs.mrp_paise if obs else None,
                member_price_paise=obs.member_price_paise if obs else None,
                in_stock=obs.in_stock if obs else None,
                observed_at=obs.observed_at if obs else None,
                freshness=freshness,
                source=obs.source if obs else None,
            )
        )
    return result


@router.patch("/listings/{listing_id}", response_model=CustomListingOut)
def update_listing(
    listing_id: str,
    req: UpdateListingRequest,
    household_id: HouseholdIdDep,
    session: SessionDep,
    now_dt: ClockDep,
) -> CustomListingOut:
    listing = session.exec(
        select(CustomListing).where(
            CustomListing.household_id == household_id,
            CustomListing.listing_id == listing_id,
        )
    ).first()
    if listing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Listing not found")

    if req.pack_label is not None:
        try:
            parse_pack(req.pack_label)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=f"Invalid pack_label: {req.pack_label}") from e
        listing.pack_label = req.pack_label

    if req.category is not None:
        category_slug = req.category.strip().lower()
        if not re.fullmatch(r"[a-z0-9_]{1,30}", category_slug):
            raise HTTPException(
                status_code=422,
                detail="Category must be a lowercase slug [a-z0-9_] between 1 and 30 characters",
            )
        listing.category = category_slug

    if req.family_key is not None:
        family_slug = req.family_key.strip().lower()
        if not re.fullmatch(r"[a-z0-9_]{1,40}", family_slug):
            raise HTTPException(
                status_code=422,
                detail="Family key must be a lowercase slug [a-z0-9_] between 1 and 40 characters",
            )
        listing.family_key = family_slug

    if req.title is not None:
        listing.title = req.title
    if req.brand is not None:
        listing.brand = req.brand
    if req.icon is not None:
        listing.icon = req.icon
    if req.archived is not None:
        listing.archived = req.archived

    session.add(listing)
    session.commit()
    session.refresh(listing)

    # Get latest observation
    obs = session.exec(
        select(PriceObservation)
        .where(
            PriceObservation.household_id == household_id,
            PriceObservation.listing_id == listing.listing_id,
        )
        .order_by(col(PriceObservation.observed_at).desc(), col(PriceObservation.id).desc())
    ).first()

    freshness = compute_freshness(listing.platform, obs.observed_at, now_dt) if obs else None

    assert listing.id is not None
    return CustomListingOut(
        id=listing.id,
        household_id=listing.household_id,
        listing_id=listing.listing_id,
        platform=listing.platform,  # type: ignore[arg-type]
        sku=listing.sku,
        url=listing.url,
        title=listing.title,
        brand=listing.brand,
        pack_label=listing.pack_label,
        category=listing.category,
        product_key=listing.product_key,
        family_key=listing.family_key,
        icon=listing.icon,
        archived=listing.archived,
        created_at=listing.created_at,
        listed_paise=obs.listed_paise if obs else None,
        mrp_paise=obs.mrp_paise if obs else None,
        member_price_paise=obs.member_price_paise if obs else None,
        in_stock=obs.in_stock if obs else None,
        observed_at=obs.observed_at if obs else None,
        freshness=freshness,
        source=obs.source if obs else None,
    )


@router.get("/catalog/families", response_model=list[FamilyOut])
def get_catalog_families(
    household_id: HouseholdIdDep,
    session: SessionDep,
) -> list[FamilyOut]:
    seed = load_seed()
    custom_listings = session.exec(
        select(CustomListing).where(
            CustomListing.household_id == household_id,
            CustomListing.archived.is_(False),  # type: ignore[attr-defined]
        )
    ).all()

    family_counts: dict[str, int] = {}
    family_units: dict[str, set[str]] = {}

    for s in seed:
        fam = s.family_key
        family_counts[fam] = family_counts.get(fam, 0) + 1
        family_units.setdefault(fam, set()).add(s.pack.unit)

    for c in custom_listings:
        fam = c.family_key
        family_counts[fam] = family_counts.get(fam, 0) + 1
        parsed = parse_pack(c.pack_label)
        family_units.setdefault(fam, set()).add(parsed.unit)

    result = [
        FamilyOut(
            family_key=fam,
            count=family_counts[fam],
            units=sorted(family_units[fam]),
        )
        for fam in sorted(family_counts.keys())
    ]
    return result
