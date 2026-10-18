import json
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session, col, or_, select

from app.api.v1.plans import (
    _DEFAULT_MEMBERS,
    FillerIn,
    NeedIn,
    OfferIn,
    PlansRequest,
    PlansResponse,
    run_plan,
)
from app.core import clock
from app.core.db import current_household_id, get_session
from app.core.money import Paise
from app.domain.catalog import current_listings
from app.domain.models import Basket, BasketLine, Need, PlanRun, ShoppingList
from app.domain.models import Offer as OfferModel
from app.pricing.fee_schedules import Platform
from app.pricing.landed import unit_price

router = APIRouter()

HouseholdIdDep = Annotated[int, Depends(current_household_id)]
SessionDep = Annotated[Session, Depends(get_session)]
ClockDep = Annotated[datetime, Depends(clock.now)]


class PlanListRequest(BaseModel):
    members: list[Platform] | None = None
    fillers: list[FillerIn] = Field(default_factory=list)
    max_filler_gap_paise: Paise | None = None
    rho_bp: int | None = None


class PlanRunResponse(PlansResponse):
    plan_run_id: int


class AcceptPlanRequest(BaseModel):
    label: str


class PlaceBasketRequest(BaseModel):
    actual_paid_paise: Paise
    without_offer: bool = False


class CashbackRequest(BaseModel):
    received_paise: Paise


class AddLineRequest(BaseModel):
    listing_id: str
    line_id: str


class LedgerSummaryOut(BaseModel):
    placed_count: int
    paid_paise: Paise
    offer_expected_paise: Paise
    offer_received_paise: Paise
    cashback_pending_paise: Paise


class BasketLineOut(BaseModel):
    id: int
    basket_id: int
    need_id: int | None
    listing_id: str
    line_id: str
    title: str
    pack_label: str
    packs: int
    unit_price_paise: Paise
    line_total_paise: Paise
    is_filler: bool


class BasketOut(BaseModel):
    id: int
    household_id: int
    plan_run_id: int
    platform: Platform
    status: str
    target_offer_code: str | None
    threshold_paise: Paise | None
    shortfall_paise: Paise | None
    planned_net_paise: Paise
    offer_value_expected_paise: Paise
    offers_json: str
    actual_paid_paise: Paise | None
    offer_value_received_paise: Paise | None
    placed_at: datetime | None
    settled_at: datetime | None
    created_at: datetime
    lines: list[BasketLineOut] = Field(default_factory=list)


def _basket_to_out(basket: Basket, lines: list[BasketLine]) -> BasketOut:
    return BasketOut(
        id=basket.id or 0,
        household_id=basket.household_id,
        plan_run_id=basket.plan_run_id,
        platform=basket.platform,  # type: ignore[arg-type]
        status=basket.status,
        target_offer_code=basket.target_offer_code,
        threshold_paise=basket.threshold_paise,
        shortfall_paise=basket.shortfall_paise,
        planned_net_paise=basket.planned_net_paise,
        offer_value_expected_paise=basket.offer_value_expected_paise,
        offers_json=basket.offers_json,
        actual_paid_paise=basket.actual_paid_paise,
        offer_value_received_paise=basket.offer_value_received_paise,
        placed_at=basket.placed_at,
        settled_at=basket.settled_at,
        created_at=basket.created_at,
        lines=[
            BasketLineOut(
                id=line.id or 0,
                basket_id=line.basket_id,
                need_id=line.need_id,
                listing_id=line.listing_id,
                line_id=line.line_id,
                title=line.title,
                pack_label=line.pack_label,
                packs=line.packs,
                unit_price_paise=line.unit_price_paise,
                line_total_paise=line.line_total_paise,
                is_filler=line.is_filler,
            )
            for line in lines
        ],
    )


@router.post("/lists/{list_id}/plan", response_model=PlanRunResponse)
def plan_list(
    list_id: int,
    req: PlanListRequest,
    household_id: HouseholdIdDep,
    session: SessionDep,
    now_dt: ClockDep,
) -> PlanRunResponse:
    shopping_list = session.exec(
        select(ShoppingList).where(
            ShoppingList.id == list_id, ShoppingList.household_id == household_id
        )
    ).first()
    if shopping_list is None:
        raise HTTPException(status_code=404, detail="Shopping list not found")

    open_needs = session.exec(
        select(Need).where(
            Need.list_id == list_id,
            Need.status == "open",
        )
    ).all()
    if not open_needs:
        raise HTTPException(
            status_code=422,
            detail="No open needs on this shopping list",
        )

    valid_platforms: set[str] = {"amazon", "flipkart", "blinkit", "instamart", "zepto"}
    needs_in: list[NeedIn] = []
    for n in open_needs:
        lock_plat: Platform | None = (
            n.lock_platform if n.lock_platform in valid_platforms else None  # type: ignore[assignment]
        )
        needs_in.append(
            NeedIn(
                line_id=n.line_id,
                product_key=n.product_key,
                family_key=n.family_key,
                quantity=n.quantity,
                qty=n.qty,
                need_by_minutes=n.need_by_minutes,
                lock_platform=lock_plat,
            )
        )

    today = now_dt.date()
    active_offers = session.exec(
        select(OfferModel).where(
            OfferModel.household_id == household_id,
            col(OfferModel.archived).is_(False),
            OfferModel.uses_left > 0,
            or_(col(OfferModel.valid_to).is_(None), col(OfferModel.valid_to) >= today),
        )
    ).all()

    offers_in: list[OfferIn] = []
    for off in active_offers:
        tiers_raw = json.loads(off.tiers_json) if off.tiers_json else []
        tiers = [tuple(t) for t in tiers_raw]
        cats = json.loads(off.eligible_categories_json) if off.eligible_categories_json else None
        offers_in.append(
            OfferIn(
                id=off.code,
                platform=off.platform,  # type: ignore[arg-type]
                kind=off.kind,  # type: ignore[arg-type]
                min_order_paise=off.min_order_paise,
                value_paise=off.value_paise,
                rate_bp=off.rate_bp,
                cap_paise=off.cap_paise,
                tiers=tiers,
                uses_left=off.uses_left,
                stack_group=off.stack_group,
                value_type=off.value_type,  # type: ignore[arg-type]
                multiplier_bp=off.multiplier_bp,
                eligible_categories=cats,
            )
        )

    members = req.members if req.members is not None else list(_DEFAULT_MEMBERS)
    plans_req = PlansRequest(
        members=members,
        needs=needs_in,
        offers=offers_in,
        fillers=req.fillers,
        max_filler_gap_paise=req.max_filler_gap_paise,
        rho_bp=req.rho_bp,
    )

    plans_resp = run_plan(
        plans_req,
        session=session,
        household_id=household_id,
        now_dt=now_dt,
    )

    plan_run = PlanRun(
        household_id=household_id,
        list_id=list_id,
        request_json=plans_req.model_dump_json(),
        response_json=plans_resp.model_dump_json(),
        accepted_label=None,
        created_at=now_dt,
    )
    session.add(plan_run)
    session.commit()
    session.refresh(plan_run)

    return PlanRunResponse(
        plan_run_id=plan_run.id or 0,
        baseline=plans_resp.baseline,
        plans=plans_resp.plans,
    )


@router.post("/plan-runs/{id}/accept", response_model=list[BasketOut])
def accept_plan_run(
    id: int,
    req: AcceptPlanRequest,
    household_id: HouseholdIdDep,
    session: SessionDep,
    now_dt: ClockDep,
) -> list[BasketOut]:
    plan_run = session.exec(
        select(PlanRun).where(PlanRun.id == id, PlanRun.household_id == household_id)
    ).first()
    if plan_run is None:
        raise HTTPException(status_code=404, detail="Plan run not found")

    if plan_run.accepted_label is not None:
        raise HTTPException(
            status_code=409,
            detail="Plan run already accepted",
        )

    resp_data = json.loads(plan_run.response_json)
    plan_choice = next(
        (p for p in resp_data.get("plans", []) if p.get("label") == req.label), None
    )
    if plan_choice is None:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown plan label: {req.label}",
        )

    req_data = json.loads(plan_run.request_json)
    offers_by_id = {o["id"]: o for o in req_data.get("offers", [])}

    needs = session.exec(
        select(Need).where(Need.list_id == plan_run.list_id)
    ).all()
    need_by_line_id = {n.line_id: n for n in needs}

    created_baskets: list[tuple[Basket, list[BasketLine]]] = []

    for order in plan_choice.get("orders", []):
        order_status = "pending" if order.get("status") == "pending" else "ready"
        target_offer_code = order.get("target_offer_id")
        threshold_paise: int | None = None
        if target_offer_code and target_offer_code in offers_by_id:
            threshold_paise = offers_by_id[target_offer_code].get("min_order_paise")
        elif order_status == "pending" and order.get("shortfall_paise") is not None:
            threshold_paise = order.get("subtotal_paise", 0) + order.get("shortfall_paise", 0)

        applied_offers = order.get("offers_applied", [])
        expected_offer_val = sum(a.get("effective_value_paise", 0) for a in applied_offers)
        offers_codes = [a.get("offer_id") for a in applied_offers]

        basket = Basket(
            household_id=household_id,
            plan_run_id=plan_run.id or 0,
            platform=order["platform"],
            status=order_status,
            target_offer_code=target_offer_code,
            threshold_paise=threshold_paise,
            shortfall_paise=order.get("shortfall_paise"),
            planned_net_paise=order["net_paise"],
            offer_value_expected_paise=expected_offer_val,
            offers_json=json.dumps(offers_codes),
            actual_paid_paise=None,
            offer_value_received_paise=None,
            placed_at=None,
            settled_at=None,
            created_at=now_dt,
        )
        session.add(basket)
        session.flush()

        b_lines: list[BasketLine] = []
        for line in order.get("lines", []):
            is_filler = line.get("is_filler", False)
            need_id: int | None = None
            if not is_filler:
                line_id = line.get("line_id")
                if line_id in need_by_line_id:
                    need_obj = need_by_line_id[line_id]
                    need_id = need_obj.id
                    need_obj.status = "planned"
                    need_obj.updated_at = now_dt
                    session.add(need_obj)

            b_line = BasketLine(
                basket_id=basket.id or 0,
                need_id=need_id,
                listing_id=line["listing_id"],
                line_id=line["line_id"],
                title=line["title"],
                pack_label=line["pack_label"],
                packs=line.get("packs", 1),
                unit_price_paise=line["unit_price_paise"],
                line_total_paise=line["line_total_paise"],
                is_filler=is_filler,
            )
            session.add(b_line)
            b_lines.append(b_line)

        created_baskets.append((basket, b_lines))

    plan_run.accepted_label = req.label
    session.add(plan_run)
    session.commit()

    for b, basket_lines in created_baskets:
        session.refresh(b)
        for bl in basket_lines:
            session.refresh(bl)

    return [_basket_to_out(b, blines) for b, blines in created_baskets]


@router.get("/baskets", response_model=list[BasketOut])
def get_baskets(
    household_id: HouseholdIdDep,
    session: SessionDep,
    status: str | None = None,
) -> list[BasketOut]:
    query = select(Basket).where(Basket.household_id == household_id)
    if status is not None:
        query = query.where(Basket.status == status)
    query = query.order_by(col(Basket.id).desc())
    baskets = session.exec(query).all()

    result: list[BasketOut] = []
    for b in baskets:
        lines = session.exec(select(BasketLine).where(BasketLine.basket_id == b.id)).all()
        result.append(_basket_to_out(b, list(lines)))
    return result


@router.get("/baskets/{id}", response_model=BasketOut)
def get_basket(
    id: int,
    household_id: HouseholdIdDep,
    session: SessionDep,
) -> BasketOut:
    basket = session.exec(
        select(Basket).where(Basket.id == id, Basket.household_id == household_id)
    ).first()
    if basket is None:
        raise HTTPException(status_code=404, detail="Basket not found")
    lines = session.exec(select(BasketLine).where(BasketLine.basket_id == basket.id)).all()
    return _basket_to_out(basket, list(lines))


@router.post("/baskets/{id}/place", response_model=BasketOut)
def place_basket(
    id: int,
    req: PlaceBasketRequest,
    household_id: HouseholdIdDep,
    session: SessionDep,
    now_dt: ClockDep,
) -> BasketOut:
    if req.actual_paid_paise < 0:
        raise HTTPException(
            status_code=422,
            detail="actual_paid_paise must be non-negative",
        )

    basket = session.exec(
        select(Basket).where(Basket.id == id, Basket.household_id == household_id)
    ).first()
    if basket is None:
        raise HTTPException(status_code=404, detail="Basket not found")

    if basket.status == "ready":
        if req.without_offer:
            basket.offer_value_expected_paise = 0
    elif basket.status == "pending":
        if not req.without_offer:
            raise HTTPException(
                status_code=409,
                detail="Pending basket can only be placed with without_offer: true",
            )
        basket.offer_value_expected_paise = 0
    else:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot place basket with status '{basket.status}'",
        )

    if basket.status == "ready" and not req.without_offer:
        applied_codes: list[str] = json.loads(basket.offers_json) if basket.offers_json else []
        for code in applied_codes:
            offer_obj = session.exec(
                select(OfferModel).where(
                    OfferModel.household_id == household_id,
                    OfferModel.code == code,
                    col(OfferModel.archived).is_(False),
                )
            ).first()
            if offer_obj is not None:
                offer_obj.uses_left = max(0, offer_obj.uses_left - 1)
                session.add(offer_obj)

    basket.status = "placed"
    basket.actual_paid_paise = req.actual_paid_paise
    basket.placed_at = now_dt

    lines = session.exec(select(BasketLine).where(BasketLine.basket_id == basket.id)).all()
    for line in lines:
        if line.need_id is not None:
            need = session.get(Need, line.need_id)
            if need is not None:
                need.status = "bought"
                need.updated_at = now_dt
                session.add(need)

    session.add(basket)
    session.commit()
    session.refresh(basket)
    return _basket_to_out(basket, list(lines))


@router.post("/baskets/{id}/cashback", response_model=BasketOut)
def record_cashback(
    id: int,
    req: CashbackRequest,
    household_id: HouseholdIdDep,
    session: SessionDep,
    now_dt: ClockDep,
) -> BasketOut:
    if req.received_paise < 0:
        raise HTTPException(
            status_code=422,
            detail="received_paise must be non-negative",
        )

    basket = session.exec(
        select(Basket).where(Basket.id == id, Basket.household_id == household_id)
    ).first()
    if basket is None:
        raise HTTPException(status_code=404, detail="Basket not found")

    if basket.status != "placed":
        raise HTTPException(
            status_code=409,
            detail=f"Cashback can only be recorded on placed baskets, current status: {basket.status}",
        )

    basket.status = "settled"
    basket.offer_value_received_paise = req.received_paise
    basket.settled_at = now_dt

    session.add(basket)
    session.commit()
    session.refresh(basket)

    lines = session.exec(select(BasketLine).where(BasketLine.basket_id == basket.id)).all()
    return _basket_to_out(basket, list(lines))


@router.post("/baskets/{id}/release", response_model=BasketOut)
def release_basket(
    id: int,
    household_id: HouseholdIdDep,
    session: SessionDep,
    now_dt: ClockDep,
) -> BasketOut:
    basket = session.exec(
        select(Basket).where(Basket.id == id, Basket.household_id == household_id)
    ).first()
    if basket is None:
        raise HTTPException(status_code=404, detail="Basket not found")

    if basket.status != "pending":
        raise HTTPException(
            status_code=409,
            detail=f"Only pending baskets can be released, current status: {basket.status}",
        )

    basket.status = "released"

    lines = session.exec(select(BasketLine).where(BasketLine.basket_id == basket.id)).all()
    for line in lines:
        if line.need_id is not None:
            need = session.get(Need, line.need_id)
            if need is not None:
                need.status = "open"
                need.updated_at = now_dt
                session.add(need)

    session.add(basket)
    session.commit()
    session.refresh(basket)
    return _basket_to_out(basket, list(lines))


@router.post("/baskets/{id}/lines", response_model=BasketOut)
def add_basket_line(
    id: int,
    req: AddLineRequest,
    household_id: HouseholdIdDep,
    session: SessionDep,
    now_dt: ClockDep,
) -> BasketOut:
    basket = session.exec(
        select(Basket).where(Basket.id == id, Basket.household_id == household_id)
    ).first()
    if basket is None:
        raise HTTPException(status_code=404, detail="Basket not found")

    if basket.status != "pending":
        raise HTTPException(
            status_code=409,
            detail=f"Lines can only be added to pending baskets, current status: {basket.status}",
        )

    current = current_listings(session=session, household_id=household_id, now=now_dt)
    curr = next((item for item in current if item.listing.id == req.listing_id), None)
    if curr is None:
        raise HTTPException(
            status_code=422,
            detail=f"Listing not found: {req.listing_id}",
        )
    listing = curr.listing

    if listing.platform != basket.platform:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Listing platform '{listing.platform}' does not match basket platform '{basket.platform}'"
            ),
        )

    plan_run = session.get(PlanRun, basket.plan_run_id)
    is_member = False
    if plan_run is not None:
        try:
            req_data = json.loads(plan_run.request_json)
            members = req_data.get("members", _DEFAULT_MEMBERS)
            is_member = listing.platform in members
        except Exception:
            is_member = listing.platform in _DEFAULT_MEMBERS
    else:
        is_member = listing.platform in _DEFAULT_MEMBERS

    price = unit_price(listing.item_price(), is_member)

    new_line = BasketLine(
        basket_id=basket.id or 0,
        need_id=None,
        listing_id=listing.id,
        line_id=req.line_id,
        title=listing.title,
        pack_label=listing.pack_label,
        packs=1,
        unit_price_paise=price,
        line_total_paise=price * 1,
        is_filler=True,
    )
    session.add(new_line)
    session.flush()

    all_lines = session.exec(select(BasketLine).where(BasketLine.basket_id == basket.id)).all()
    subtotal = sum(bline.line_total_paise for bline in all_lines)

    threshold = basket.threshold_paise or 0
    if subtotal >= threshold:
        basket.status = "ready"
        basket.shortfall_paise = 0
    else:
        basket.shortfall_paise = threshold - subtotal

    session.add(basket)
    session.commit()
    session.refresh(basket)

    return _basket_to_out(basket, list(all_lines))


@router.get("/ledger/summary", response_model=LedgerSummaryOut)
def get_ledger_summary(
    household_id: HouseholdIdDep,
    session: SessionDep,
    now_dt: ClockDep,
    month: str | None = None,
) -> LedgerSummaryOut:
    target_month = month or now_dt.strftime("%Y-%m")
    try:
        parts = target_month.split("-")
        if len(parts) != 2 or len(parts[0]) != 4 or len(parts[1]) != 2:
            raise ValueError("Invalid format")
        int(parts[0])
        int(parts[1])
    except Exception as err:
        raise HTTPException(
            status_code=422,
            detail="Invalid month format, expected YYYY-MM",
        ) from err

    baskets = session.exec(
        select(Basket).where(
            Basket.household_id == household_id,
            col(Basket.placed_at).is_not(None),
        )
    ).all()

    month_baskets = [
        b
        for b in baskets
        if b.placed_at is not None and b.placed_at.strftime("%Y-%m") == target_month
    ]

    placed_count = len(month_baskets)
    paid_paise = sum(b.actual_paid_paise or 0 for b in month_baskets)
    offer_expected_paise = sum(b.offer_value_expected_paise or 0 for b in month_baskets)
    offer_received_paise = sum(b.offer_value_received_paise or 0 for b in month_baskets)
    cashback_pending_paise = sum(
        b.offer_value_expected_paise or 0 for b in month_baskets if b.status == "placed"
    )

    return LedgerSummaryOut(
        placed_count=placed_count,
        paid_paise=paid_paise,
        offer_expected_paise=offer_expected_paise,
        offer_received_paise=offer_received_paise,
        cashback_pending_paise=cashback_pending_paise,
    )
