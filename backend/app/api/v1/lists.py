from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlmodel import Session, col, func, select

from app.core.db import current_household_id, get_session
from app.domain.models import Need, ShoppingList
from app.domain.need_rules import validate_need

router = APIRouter()

HouseholdIdDep = Annotated[int, Depends(current_household_id)]
SessionDep = Annotated[Session, Depends(get_session)]


class ShoppingListCreate(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    kind: Literal["quick", "monthly", "event"]


class ShoppingListUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=60)
    archived: bool | None = None


class NeedOut(BaseModel):
    id: int
    list_id: int
    line_id: str
    product_key: str | None
    family_key: str | None
    quantity: str | None
    qty: int
    need_by_minutes: int | None
    lock_platform: str | None
    status: str
    created_at: datetime
    updated_at: datetime


class ShoppingListSummaryOut(BaseModel):
    id: int
    household_id: int
    name: str
    kind: str
    archived: bool
    created_at: datetime
    open_needs: int


class ShoppingListDetailOut(BaseModel):
    id: int
    household_id: int
    name: str
    kind: str
    archived: bool
    created_at: datetime
    needs: list[NeedOut]


class NeedCreate(BaseModel):
    line_id: str = Field(min_length=1, max_length=80)
    product_key: str | None = None
    family_key: str | None = None
    quantity: str | None = None
    qty: int = Field(default=1, ge=1, le=99)
    need_by_minutes: int | None = None
    lock_platform: str | None = None


class NeedUpdate(BaseModel):
    line_id: str | None = Field(default=None, min_length=1, max_length=80)
    product_key: str | None = None
    family_key: str | None = None
    quantity: str | None = None
    qty: int | None = Field(default=None, ge=1, le=99)
    need_by_minutes: int | None = None
    lock_platform: str | None = None
    status: Literal["open", "planned", "bought", "dropped"] | None = None


@router.get("/lists", response_model=list[ShoppingListSummaryOut])
def get_lists(
    household_id: HouseholdIdDep,
    session: SessionDep,
) -> list[ShoppingListSummaryOut]:
    stmt = (
        select(ShoppingList)
        .where(
            ShoppingList.household_id == household_id,
            ShoppingList.archived.is_(False),  # type: ignore[attr-defined]
        )
        .order_by(
            col(ShoppingList.created_at).desc(),
            col(ShoppingList.id).desc(),
        )
    )
    lists = session.exec(stmt).all()

    # Calculate open_needs per list
    results: list[ShoppingListSummaryOut] = []
    for s_list in lists:
        assert s_list.id is not None
        count_stmt = select(func.count(col(Need.id))).where(
            Need.list_id == s_list.id,
            Need.status == "open",
        )
        open_count = session.exec(count_stmt).one() or 0
        results.append(
            ShoppingListSummaryOut(
                id=s_list.id,
                household_id=s_list.household_id,
                name=s_list.name,
                kind=s_list.kind,
                archived=s_list.archived,
                created_at=s_list.created_at,
                open_needs=open_count,
            )
        )
    return results


@router.post(
    "/lists",
    response_model=ShoppingListSummaryOut,
    status_code=status.HTTP_201_CREATED,
)
def create_list(
    req: ShoppingListCreate,
    household_id: HouseholdIdDep,
    session: SessionDep,
) -> ShoppingListSummaryOut:
    s_list = ShoppingList(
        household_id=household_id,
        name=req.name,
        kind=req.kind,
        archived=False,
    )
    session.add(s_list)
    session.commit()
    session.refresh(s_list)
    assert s_list.id is not None
    return ShoppingListSummaryOut(
        id=s_list.id,
        household_id=s_list.household_id,
        name=s_list.name,
        kind=s_list.kind,
        archived=s_list.archived,
        created_at=s_list.created_at,
        open_needs=0,
    )


@router.get("/lists/{id}", response_model=ShoppingListDetailOut)
def get_list(
    id: int,
    household_id: HouseholdIdDep,
    session: SessionDep,
) -> ShoppingListDetailOut:
    s_list = session.exec(
        select(ShoppingList).where(
            ShoppingList.id == id,
            ShoppingList.household_id == household_id,
        )
    ).first()
    if s_list is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="List not found",
        )

    needs = session.exec(
        select(Need)
        .where(Need.list_id == id)
        .order_by(col(Need.created_at).asc(), col(Need.id).asc())
    ).all()

    needs_out = [
        NeedOut(
            id=n.id,  # type: ignore[arg-type]
            list_id=n.list_id,
            line_id=n.line_id,
            product_key=n.product_key,
            family_key=n.family_key,
            quantity=n.quantity,
            qty=n.qty,
            need_by_minutes=n.need_by_minutes,
            lock_platform=n.lock_platform,
            status=n.status,
            created_at=n.created_at,
            updated_at=n.updated_at,
        )
        for n in needs
    ]

    assert s_list.id is not None
    return ShoppingListDetailOut(
        id=s_list.id,
        household_id=s_list.household_id,
        name=s_list.name,
        kind=s_list.kind,
        archived=s_list.archived,
        created_at=s_list.created_at,
        needs=needs_out,
    )


@router.patch("/lists/{id}", response_model=ShoppingListSummaryOut)
def update_list(
    id: int,
    req: ShoppingListUpdate,
    household_id: HouseholdIdDep,
    session: SessionDep,
) -> ShoppingListSummaryOut:
    s_list = session.exec(
        select(ShoppingList).where(
            ShoppingList.id == id,
            ShoppingList.household_id == household_id,
        )
    ).first()
    if s_list is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="List not found",
        )

    if req.name is not None:
        s_list.name = req.name
    if req.archived is not None:
        s_list.archived = req.archived

    session.add(s_list)
    session.commit()
    session.refresh(s_list)

    count_stmt = select(func.count(col(Need.id))).where(
        Need.list_id == s_list.id,
        Need.status == "open",
    )
    open_count = session.exec(count_stmt).one() or 0

    assert s_list.id is not None
    return ShoppingListSummaryOut(
        id=s_list.id,
        household_id=s_list.household_id,
        name=s_list.name,
        kind=s_list.kind,
        archived=s_list.archived,
        created_at=s_list.created_at,
        open_needs=open_count,
    )


@router.post(
    "/lists/{id}/needs",
    response_model=NeedOut,
    status_code=status.HTTP_201_CREATED,
)
def create_need(
    id: int,
    req: NeedCreate,
    household_id: HouseholdIdDep,
    session: SessionDep,
) -> NeedOut:
    s_list = session.exec(
        select(ShoppingList).where(
            ShoppingList.id == id,
            ShoppingList.household_id == household_id,
        )
    ).first()
    if s_list is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="List not found",
        )

    # Check duplicate line_id in list
    existing = session.exec(
        select(Need).where(
            Need.list_id == id,
            Need.line_id == req.line_id,
        )
    ).first()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Duplicate line_id: {req.line_id}",
        )

    try:
        validate_need(
            product_key=req.product_key,
            family_key=req.family_key,
            quantity=req.quantity,
            qty=req.qty,
            line_id=req.line_id,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=422,
            detail=str(e),
        ) from e

    need = Need(
        list_id=id,
        line_id=req.line_id,
        product_key=req.product_key,
        family_key=req.family_key,
        quantity=req.quantity,
        qty=req.qty,
        need_by_minutes=req.need_by_minutes,
        lock_platform=req.lock_platform,
        status="open",
    )
    session.add(need)
    session.commit()
    session.refresh(need)

    return NeedOut(
        id=need.id,  # type: ignore[arg-type]
        list_id=need.list_id,
        line_id=need.line_id,
        product_key=need.product_key,
        family_key=need.family_key,
        quantity=need.quantity,
        qty=need.qty,
        need_by_minutes=need.need_by_minutes,
        lock_platform=need.lock_platform,
        status=need.status,
        created_at=need.created_at,
        updated_at=need.updated_at,
    )


@router.patch("/needs/{id}", response_model=NeedOut)
def update_need(
    id: int,
    req: NeedUpdate,
    household_id: HouseholdIdDep,
    session: SessionDep,
) -> NeedOut:
    need = session.exec(select(Need).where(Need.id == id)).first()
    if need is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Need not found",
        )

    # Check ownership via shopping list
    s_list = session.exec(
        select(ShoppingList).where(
            ShoppingList.id == need.list_id,
            ShoppingList.household_id == household_id,
        )
    ).first()
    if s_list is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Need not found",
        )

    req_fields = req.model_fields_set
    new_line_id = req.line_id if req.line_id is not None else need.line_id
    if req.line_id is not None and req.line_id != need.line_id:
        existing = session.exec(
            select(Need).where(
                Need.list_id == need.list_id,
                Need.line_id == req.line_id,
            )
        ).first()
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Duplicate line_id: {req.line_id}",
            )

    new_pk = req.product_key if "product_key" in req_fields else need.product_key
    new_fk = req.family_key if "family_key" in req_fields else need.family_key
    new_qty = req.qty if req.qty is not None else need.qty
    new_quantity = req.quantity if "quantity" in req_fields else need.quantity
    new_nbm = (
        req.need_by_minutes if "need_by_minutes" in req_fields else need.need_by_minutes
    )
    new_lp = (
        req.lock_platform if "lock_platform" in req_fields else need.lock_platform
    )
    new_status = req.status if req.status is not None else need.status

    try:
        validate_need(
            product_key=new_pk,
            family_key=new_fk,
            quantity=new_quantity,
            qty=new_qty,
            line_id=new_line_id,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=422,
            detail=str(e),
        ) from e

    need.line_id = new_line_id
    need.product_key = new_pk
    need.family_key = new_fk
    need.quantity = new_quantity
    need.qty = new_qty
    need.need_by_minutes = new_nbm
    need.lock_platform = new_lp
    need.status = new_status
    need.updated_at = datetime.now(UTC)

    session.add(need)
    session.commit()
    session.refresh(need)

    return NeedOut(
        id=need.id,  # type: ignore[arg-type]
        list_id=need.list_id,
        line_id=need.line_id,
        product_key=need.product_key,
        family_key=need.family_key,
        quantity=need.quantity,
        qty=need.qty,
        need_by_minutes=need.need_by_minutes,
        lock_platform=need.lock_platform,
        status=need.status,
        created_at=need.created_at,
        updated_at=need.updated_at,
    )


@router.delete("/needs/{id}", response_model=NeedOut)
def delete_need(
    id: int,
    household_id: HouseholdIdDep,
    session: SessionDep,
) -> NeedOut:
    need = session.exec(select(Need).where(Need.id == id)).first()
    if need is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Need not found",
        )

    s_list = session.exec(
        select(ShoppingList).where(
            ShoppingList.id == need.list_id,
            ShoppingList.household_id == household_id,
        )
    ).first()
    if s_list is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Need not found",
        )

    need.status = "dropped"
    need.updated_at = datetime.now(UTC)
    session.add(need)
    session.commit()
    session.refresh(need)

    return NeedOut(
        id=need.id,  # type: ignore[arg-type]
        list_id=need.list_id,
        line_id=need.line_id,
        product_key=need.product_key,
        family_key=need.family_key,
        quantity=need.quantity,
        qty=need.qty,
        need_by_minutes=need.need_by_minutes,
        lock_platform=need.lock_platform,
        status=need.status,
        created_at=need.created_at,
        updated_at=need.updated_at,
    )
