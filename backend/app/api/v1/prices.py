from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, model_validator
from sqlmodel import Session, col, select

from app.core import clock
from app.core.db import current_household_id, get_session
from app.core.money import Paise
from app.domain.catalog import all_listings
from app.domain.models import PriceObservation

router = APIRouter()

HouseholdIdDep = Annotated[int, Depends(current_household_id)]
SessionDep = Annotated[Session, Depends(get_session)]
ClockDep = Annotated[datetime, Depends(clock.now)]


class PriceObservationCreate(BaseModel):
    listing_id: str
    listed_paise: Paise
    mrp_paise: Paise
    member_price_paise: Paise | None = None
    in_stock: bool = True
    eta_minutes: int | None = None
    note: str | None = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def validate_fields(self) -> "PriceObservationCreate":
        if self.listed_paise <= 0:
            raise ValueError(f"listed_paise must be positive, got {self.listed_paise}")
        if self.mrp_paise < self.listed_paise:
            raise ValueError(
                f"mrp_paise ({self.mrp_paise}) cannot be less than listed_paise ({self.listed_paise})"
            )
        if self.member_price_paise is not None:
            if self.member_price_paise < 0:
                raise ValueError("member_price_paise cannot be negative")
            if self.member_price_paise > self.listed_paise:
                raise ValueError(
                    f"member_price_paise ({self.member_price_paise}) "
                    f"cannot exceed listed_paise ({self.listed_paise})"
                )
        if self.eta_minutes is not None and self.eta_minutes < 0:
            raise ValueError(f"eta_minutes cannot be negative, got {self.eta_minutes}")
        return self


class PriceObservationOut(BaseModel):
    id: int
    household_id: int
    listing_id: str
    listed_paise: Paise
    mrp_paise: Paise
    member_price_paise: Paise | None
    in_stock: bool
    eta_minutes: int | None
    source: str
    note: str | None
    observed_at: datetime


@router.post("/prices", response_model=PriceObservationOut, status_code=201)
def create_price_observation(
    req: PriceObservationCreate,
    household_id: HouseholdIdDep,
    session: SessionDep,
    now_dt: ClockDep,
) -> PriceObservation:
    valid_ids = {item.id for item in all_listings(session=session, household_id=household_id)}
    if req.listing_id not in valid_ids:
        raise HTTPException(status_code=422, detail=f"Unknown listing_id: {req.listing_id}")

    obs = PriceObservation(
        household_id=household_id,
        listing_id=req.listing_id,
        listed_paise=req.listed_paise,
        mrp_paise=req.mrp_paise,
        member_price_paise=req.member_price_paise,
        in_stock=req.in_stock,
        eta_minutes=req.eta_minutes,
        source="manual",
        note=req.note,
        observed_at=now_dt,
    )
    session.add(obs)
    session.commit()
    session.refresh(obs)
    return obs


@router.get("/prices", response_model=list[PriceObservationOut])
def get_price_observations(
    household_id: HouseholdIdDep,
    session: SessionDep,
    listing_id: str = Query(...),
) -> list[PriceObservation]:
    valid_ids = {item.id for item in all_listings(session=session, household_id=household_id)}
    if listing_id not in valid_ids:
        raise HTTPException(status_code=422, detail=f"Unknown listing_id: {listing_id}")

    observations = session.exec(
        select(PriceObservation)
        .where(
            PriceObservation.household_id == household_id,
            PriceObservation.listing_id == listing_id,
        )
        .order_by(
            col(PriceObservation.observed_at).desc(),
            col(PriceObservation.id).desc(),
        )
        .limit(50)
    ).all()
    return list(observations)
