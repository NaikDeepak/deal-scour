import json
from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlmodel import Session, col, select

from app.core.db import current_household_id, get_session
from app.core.money import Paise
from app.domain.models import Offer as OfferModel
from app.optimizer.contract import Offer as OptimizerOffer
from app.optimizer.contract import OfferKind, ValueType
from app.pricing.fee_schedules import Platform

router = APIRouter()

HouseholdIdDep = Annotated[int, Depends(current_household_id)]
SessionDep = Annotated[Session, Depends(get_session)]


class OfferCreate(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=20)
    id: str | None = None
    platform: Platform
    kind: OfferKind
    min_order_paise: Paise = 0
    value_paise: Paise = 0
    rate_bp: int = 0
    cap_paise: Paise | None = None
    tiers: list[tuple[Paise, Paise]] = Field(default_factory=list)
    uses_left: int = 1
    stack_group: str = "platform_coupon"
    value_type: ValueType = "cash"
    multiplier_bp: int | None = None
    eligible_categories: list[str] | None = None
    valid_to: date | None = None
    note: str | None = Field(default=None, max_length=200)

    @property
    def offer_code(self) -> str:
        c = self.code or self.id
        if not c:
            raise ValueError("code or id is required")
        return c


class OfferUpdate(BaseModel):
    uses_left: int | None = Field(default=None, ge=0)
    valid_to: date | None = None
    note: str | None = Field(default=None, max_length=200)
    archived: bool | None = None


class OfferOut(BaseModel):
    id: int
    household_id: int
    code: str
    platform: Platform
    kind: OfferKind
    min_order_paise: Paise
    value_paise: Paise
    rate_bp: int
    cap_paise: Paise | None
    tiers: list[tuple[Paise, Paise]]
    uses_left: int
    stack_group: str
    value_type: ValueType
    multiplier_bp: int | None
    eligible_categories: list[str] | None
    valid_to: date | None
    note: str | None
    archived: bool
    created_at: datetime


def _row_to_offer_out(row: OfferModel) -> OfferOut:
    tiers_raw = json.loads(row.tiers_json) if row.tiers_json else []
    tiers = [(int(t[0]), int(t[1])) for t in tiers_raw]
    cats = (
        json.loads(row.eligible_categories_json)
        if row.eligible_categories_json is not None
        else None
    )
    assert row.id is not None
    return OfferOut(
        id=row.id,
        household_id=row.household_id,
        code=row.code,
        platform=row.platform,  # type: ignore[arg-type]
        kind=row.kind,  # type: ignore[arg-type]
        min_order_paise=row.min_order_paise,
        value_paise=row.value_paise,
        rate_bp=row.rate_bp,
        cap_paise=row.cap_paise,
        tiers=tiers,
        uses_left=row.uses_left,
        stack_group=row.stack_group,
        value_type=row.value_type,  # type: ignore[arg-type]
        multiplier_bp=row.multiplier_bp,
        eligible_categories=cats,
        valid_to=row.valid_to,
        note=row.note,
        archived=row.archived,
        created_at=row.created_at,
    )


@router.get("/offers", response_model=list[OfferOut])
def get_offers(
    household_id: HouseholdIdDep,
    session: SessionDep,
    include_archived: bool = False,
) -> list[OfferOut]:
    stmt = select(OfferModel).where(OfferModel.household_id == household_id)
    if not include_archived:
        stmt = stmt.where(OfferModel.archived.is_(False))  # type: ignore[attr-defined]

    stmt = stmt.order_by(col(OfferModel.created_at).desc(), col(OfferModel.id).desc())
    rows = session.exec(stmt).all()
    return [_row_to_offer_out(row) for row in rows]


@router.post(
    "/offers",
    response_model=OfferOut,
    status_code=status.HTTP_201_CREATED,
)
def create_offer(
    req: OfferCreate,
    household_id: HouseholdIdDep,
    session: SessionDep,
) -> OfferOut:
    try:
        code = req.offer_code
    except ValueError as e:
        raise HTTPException(
            status_code=422,
            detail=str(e),
        ) from e

    # Duplicate active code check
    existing = session.exec(
        select(OfferModel).where(
            OfferModel.household_id == household_id,
            OfferModel.code == code,
            OfferModel.archived.is_(False),  # type: ignore[attr-defined]
        )
    ).first()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Active offer with code '{code}' already exists",
        )

    # Validate offer by constructing optimizer Offer
    try:
        tiers_tuple = tuple((tier[0], tier[1]) for tier in req.tiers)
        cats = (
            frozenset(req.eligible_categories)
            if req.eligible_categories is not None
            else None
        )
        OptimizerOffer(
            id=code,
            platform=req.platform,
            kind=req.kind,
            min_order=req.min_order_paise,
            value=req.value_paise,
            rate_bp=req.rate_bp,
            cap=req.cap_paise,
            tiers=tiers_tuple,
            uses_left=req.uses_left,
            stack_group=req.stack_group,
            value_type=req.value_type,
            multiplier_bp=req.multiplier_bp,
            eligible_categories=cats,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=422,
            detail=str(e),
        ) from e

    tiers_json = json.dumps(req.tiers)
    cats_json = (
        json.dumps(req.eligible_categories)
        if req.eligible_categories is not None
        else None
    )

    offer_row = OfferModel(
        household_id=household_id,
        code=code,
        platform=req.platform,
        kind=req.kind,
        min_order_paise=req.min_order_paise,
        value_paise=req.value_paise,
        rate_bp=req.rate_bp,
        cap_paise=req.cap_paise,
        tiers_json=tiers_json,
        uses_left=req.uses_left,
        stack_group=req.stack_group,
        value_type=req.value_type,
        multiplier_bp=req.multiplier_bp,
        eligible_categories_json=cats_json,
        valid_to=req.valid_to,
        note=req.note,
        archived=False,
    )
    session.add(offer_row)
    session.commit()
    session.refresh(offer_row)

    return _row_to_offer_out(offer_row)


@router.patch("/offers/{id}", response_model=OfferOut)
def update_offer(
    id: int,
    req: OfferUpdate,
    household_id: HouseholdIdDep,
    session: SessionDep,
) -> OfferOut:
    offer_row = session.exec(
        select(OfferModel).where(
            OfferModel.id == id,
            OfferModel.household_id == household_id,
        )
    ).first()
    if offer_row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Offer not found",
        )

    req_fields = req.model_fields_set
    if "archived" in req_fields and req.archived is False and offer_row.archived is True:
        # Check active code conflict if unarchiving
        conflict = session.exec(
            select(OfferModel).where(
                OfferModel.household_id == household_id,
                OfferModel.code == offer_row.code,
                OfferModel.archived.is_(False),  # type: ignore[attr-defined]
            )
        ).first()
        if conflict is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Active offer with code '{offer_row.code}' already exists",
            )

    if "uses_left" in req_fields and req.uses_left is not None:
        offer_row.uses_left = req.uses_left
    if "valid_to" in req_fields:
        offer_row.valid_to = req.valid_to
    if "note" in req_fields:
        offer_row.note = req.note
    if "archived" in req_fields and req.archived is not None:
        offer_row.archived = req.archived

    session.add(offer_row)
    session.commit()
    session.refresh(offer_row)
    return _row_to_offer_out(offer_row)


@router.post("/offers/{id}/archive", response_model=OfferOut)
def archive_offer(
    id: int,
    household_id: HouseholdIdDep,
    session: SessionDep,
) -> OfferOut:
    offer_row = session.exec(
        select(OfferModel).where(
            OfferModel.id == id,
            OfferModel.household_id == household_id,
        )
    ).first()
    if offer_row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Offer not found",
        )

    offer_row.archived = True
    session.add(offer_row)
    session.commit()
    session.refresh(offer_row)
    return _row_to_offer_out(offer_row)
