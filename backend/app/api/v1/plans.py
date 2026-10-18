from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.core import clock
from app.core.db import current_household_id, get_session
from app.core.money import Paise
from app.domain.catalog import CurrentListing, SeedListing, current_listings
from app.domain.need_rules import validate_need
from app.optimizer.contract import Offer, OfferKind, ValueType
from app.optimizer.pending import (
    DEFAULT_PENDING_SETTINGS,
    Filler,
    PendingOrder,
    PendingSettings,
)
from app.optimizer.planning import Candidate, NeedLine, Plan
from app.optimizer.planset import PlanLabel, PlanSet, plan
from app.pricing.fee_schedules import Platform
from app.pricing.landed import unit_price
from app.pricing.units import parse_pack

router = APIRouter()

HouseholdIdDep = Annotated[int, Depends(current_household_id)]
SessionDep = Annotated[Session, Depends(get_session)]
ClockDep = Annotated[datetime, Depends(clock.now)]

_VALID_PLATFORMS: set[str] = {"amazon", "flipkart", "blinkit", "instamart", "zepto"}
ALL_PLATFORMS: list[Platform] = ["amazon", "flipkart", "blinkit", "instamart", "zepto"]


_DEFAULT_MEMBERS: list[Platform] = ["amazon", "instamart", "flipkart"]


class NeedIn(BaseModel):
    line_id: str
    product_key: str | None = None
    family_key: str | None = None
    quantity: str | None = None
    qty: int = Field(default=1, ge=1, le=99)
    need_by_minutes: int | None = None
    lock_platform: Platform | None = None


class OfferIn(BaseModel):
    id: str
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


class FillerIn(BaseModel):
    filler_id: str
    listing_id: str
    score: int


class PlansRequest(BaseModel):
    members: list[Platform] = Field(
        default_factory=lambda: list(_DEFAULT_MEMBERS)
    )
    needs: list[NeedIn] = Field(default_factory=list)
    offers: list[OfferIn] = Field(default_factory=list)
    fillers: list[FillerIn] = Field(default_factory=list)
    max_filler_gap_paise: Paise | None = None
    rho_bp: int | None = None


class FeesOut(BaseModel):
    delivery: Paise
    handling: Paise
    platform: Paise
    small_cart: Paise
    surge: Paise
    total: Paise


class OfferAppliedOut(BaseModel):
    offer_id: str
    face_value_paise: Paise
    effective_value_paise: Paise


class OrderLineOut(BaseModel):
    line_id: str
    listing_id: str
    title: str
    pack_label: str
    packs: int
    unit_price_paise: Paise
    line_total_paise: Paise
    is_filler: bool
    price_source: str
    freshness: str


class OrderOut(BaseModel):
    platform: Platform
    status: Literal["now", "pending"]
    lines: list[OrderLineOut]
    subtotal_paise: Paise
    fees: FeesOut
    offers_applied: list[OfferAppliedOut]
    net_paise: Paise
    shortfall_paise: Paise | None
    target_offer_id: str | None


class ReasonOut(BaseModel):
    code: str
    platform: str
    amount_paise: Paise
    line_ids: list[str]
    text: str


class PlanOut(BaseModel):
    orders: list[OrderOut]
    total_subtotal_paise: Paise
    total_fees_paise: Paise
    total_offer_value_paise: Paise
    total_net_paise: Paise
    unpriced: list[str]


class LabelledPlanOut(PlanOut):
    label: PlanLabel
    effective_cost_paise: Paise
    savings_vs_baseline_paise: Paise
    reasons: list[ReasonOut]


class PlansResponse(BaseModel):
    baseline: PlanOut
    plans: list[LabelledPlanOut]


def _build_plan_out(
    p: Plan,
    current_by_id: dict[str, CurrentListing],
    filler_ids: set[str],
    memberships: dict[Platform, bool],
    line_packs: dict[tuple[str, str], int],
    pending: tuple[PendingOrder, ...] = (),
) -> PlanOut:
    pending_by_order_idx = {pend.order_index: pend for pend in pending}
    orders_out: list[OrderOut] = []

    for order_idx, (order_lines, order_res) in enumerate(
        zip(p.orders, p.result.orders, strict=True)
    ):
        pend = pending_by_order_idx.get(order_idx)
        status: Literal["now", "pending"] = "pending" if pend is not None else "now"
        shortfall_paise = pend.shortfall if pend is not None else None
        target_offer_id = pend.target_offer_id if pend is not None else None

        lines_out: list[OrderLineOut] = []
        for pline in order_lines:
            cur = current_by_id[pline.listing_id]
            listing = cur.listing
            is_filler = pline.line_id in filler_ids
            packs = (
                1
                if is_filler
                else line_packs.get((pline.line_id, pline.listing_id), pline.qty)
            )

            single_pack_price = unit_price(listing.item_price(), memberships[listing.platform])
            lines_out.append(
                OrderLineOut(
                    line_id=pline.line_id,
                    listing_id=pline.listing_id,
                    title=listing.title,
                    pack_label=listing.pack_label,
                    packs=packs,
                    unit_price_paise=single_pack_price,
                    line_total_paise=single_pack_price * packs,
                    is_filler=is_filler,
                    price_source=cur.source,
                    freshness=cur.freshness,
                )
            )

        fees_out = FeesOut(
            delivery=order_res.fees.delivery,
            handling=order_res.fees.handling,
            platform=order_res.fees.platform,
            small_cart=order_res.fees.small_cart,
            surge=order_res.fees.surge,
            total=order_res.fees.total,
        )

        offers_applied_out = [
            OfferAppliedOut(
                offer_id=a.offer_id,
                face_value_paise=a.face_value,
                effective_value_paise=a.effective_value,
            )
            for a in order_res.applied
        ]

        orders_out.append(
            OrderOut(
                platform=order_res.platform,
                status=status,
                lines=lines_out,
                subtotal_paise=order_res.subtotal,
                fees=fees_out,
                offers_applied=offers_applied_out,
                net_paise=order_res.net,
                shortfall_paise=shortfall_paise,
                target_offer_id=target_offer_id,
            )
        )

    return PlanOut(
        orders=orders_out,
        total_subtotal_paise=p.result.total_subtotal,
        total_fees_paise=p.result.total_fees,
        total_offer_value_paise=p.result.total_offer_value,
        total_net_paise=p.result.total_net,
        unpriced=list(p.unpriced),
    )


def run_plan(
    req: PlansRequest,
    session: Session,
    household_id: int,
    now_dt: datetime,
) -> PlansResponse:
    # 1. Validate members
    members_set: set[Platform] = set()
    for m in req.members:
        if m not in _VALID_PLATFORMS:
            raise HTTPException(status_code=422, detail=f"Unknown platform in members: {m}")
        members_set.add(m)

    memberships: dict[Platform, bool] = {p: p in members_set for p in ALL_PLATFORMS}

    # Load current listings with observations applied
    current = current_listings(session=session, household_id=household_id, now=now_dt)
    current_by_id: dict[str, CurrentListing] = {cl.listing.id: cl for cl in current}
    seed_by_product: dict[str, list[SeedListing]] = {}
    seed_by_family: dict[str, list[SeedListing]] = {}
    current_by_product: dict[str, list[CurrentListing]] = {}
    current_by_family: dict[str, list[CurrentListing]] = {}
    for cur_item in current:
        seed_by_product.setdefault(cur_item.listing.product_key, []).append(cur_item.listing)
        seed_by_family.setdefault(cur_item.listing.family_key, []).append(cur_item.listing)
        current_by_product.setdefault(cur_item.listing.product_key, []).append(cur_item)
        current_by_family.setdefault(cur_item.listing.family_key, []).append(cur_item)

    # 2. Build needs
    seen_line_ids: set[str] = set()
    opt_needs: list[NeedLine] = []
    line_packs: dict[tuple[str, str], int] = {}

    try:
        for need in req.needs:
            if need.line_id in seen_line_ids:
                raise ValueError(f"Duplicate line_id: {need.line_id}")
            seen_line_ids.add(need.line_id)

            validate_need(
                product_key=need.product_key,
                family_key=need.family_key,
                quantity=need.quantity,
                qty=need.qty,
                catalog=[c.listing for c in current],
                line_id=need.line_id,
            )

            if need.product_key is not None:
                prod_current = [c for c in current_by_product.get(need.product_key, []) if c.in_stock]
                candidates = [
                    Candidate(
                        listing_id=c.listing.id,
                        platform=c.listing.platform,
                        unit_price=unit_price(c.listing.item_price(), memberships[c.listing.platform]),
                        eta_minutes=c.listing.eta_minutes,
                    )
                    for c in prod_current
                ]
                for c in prod_current:
                    line_packs[(need.line_id, c.listing.id)] = need.qty

                opt_needs.append(
                    NeedLine(
                        line_id=need.line_id,
                        category=seed_by_product[need.product_key][0].category,
                        qty=need.qty,
                        candidates=tuple(candidates),
                        need_by_minutes=need.need_by_minutes,
                        lock_platform=need.lock_platform,
                    )
                )
            else:
                assert need.family_key is not None
                assert need.quantity is not None
                parsed_pack = parse_pack(need.quantity)
                target = parsed_pack.qty * need.qty

                family_current = [c for c in current_by_family.get(need.family_key, []) if c.in_stock]
                matching_current = [
                    c for c in family_current if c.listing.pack.unit == parsed_pack.unit
                ]

                candidates = []
                for c in matching_current:
                    seed_item = c.listing
                    packs = -(-target // seed_item.pack.qty)  # integer ceil: no float overflow
                    line_packs[(need.line_id, seed_item.id)] = packs
                    base_up = unit_price(seed_item.item_price(), memberships[seed_item.platform])
                    candidates.append(
                        Candidate(
                            listing_id=seed_item.id,
                            platform=seed_item.platform,
                            unit_price=base_up * packs,
                            eta_minutes=seed_item.eta_minutes,
                        )
                    )

                opt_needs.append(
                    NeedLine(
                        line_id=need.line_id,
                        category=seed_by_family[need.family_key][0].category,
                        qty=1,
                        candidates=tuple(candidates),
                        need_by_minutes=need.need_by_minutes,
                        lock_platform=need.lock_platform,
                    )
                )

        # 3. Build offers
        opt_offers: list[Offer] = []
        seen_offer_ids: set[str] = set()
        for off in req.offers:
            if off.id in seen_offer_ids:
                raise ValueError(f"Duplicate offer id: {off.id}")
            seen_offer_ids.add(off.id)

            tiers_tuple: tuple[tuple[Paise, Paise], ...] = tuple(off.tiers)
            cats = frozenset(off.eligible_categories) if off.eligible_categories is not None else None
            opt_offers.append(
                Offer(
                    id=off.id,
                    platform=off.platform,
                    kind=off.kind,
                    min_order=off.min_order_paise,
                    value=off.value_paise,
                    rate_bp=off.rate_bp,
                    cap=off.cap_paise,
                    tiers=tiers_tuple,
                    uses_left=off.uses_left,
                    stack_group=off.stack_group,
                    value_type=off.value_type,
                    multiplier_bp=off.multiplier_bp,
                    eligible_categories=cats,
                )
            )

        # 4. Build fillers
        opt_fillers: list[Filler] = []
        filler_ids: set[str] = set()
        for f in req.fillers:
            if f.listing_id not in current_by_id:
                raise ValueError(f"Unknown filler listing_id: {f.listing_id}")
            curr = current_by_id[f.listing_id]
            if not curr.in_stock:
                continue

            if f.filler_id in filler_ids:
                raise ValueError(f"Duplicate filler_id: {f.filler_id}")
            if f.filler_id in seen_line_ids:
                raise ValueError(f"filler_id '{f.filler_id}' conflicts with need line_id")
            filler_ids.add(f.filler_id)

            listing = curr.listing
            up = unit_price(listing.item_price(), memberships[listing.platform])
            opt_fillers.append(
                Filler(
                    filler_id=f.filler_id,
                    listing_id=listing.id,
                    platform=listing.platform,
                    category=listing.category,
                    unit_price=up,
                    score=f.score,
                )
            )

        # 5. PendingSettings overrides
        pending_kwargs: dict[str, int] = {}
        if req.max_filler_gap_paise is not None:
            pending_kwargs["max_filler_gap"] = req.max_filler_gap_paise
        if req.rho_bp is not None:
            pending_kwargs["rho_bp"] = req.rho_bp

        pending_settings = (
            PendingSettings(**pending_kwargs)
            if pending_kwargs
            else DEFAULT_PENDING_SETTINGS
        )

        # 6. Execute optimizer
        planset: PlanSet = plan(
            needs=opt_needs,
            offers=opt_offers,
            memberships=memberships,
            fillers=opt_fillers,
            pending_settings=pending_settings,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    # 7. Map response
    baseline_out = _build_plan_out(
        p=planset.baseline,
        current_by_id=current_by_id,
        filler_ids=filler_ids,
        memberships=memberships,
        line_packs=line_packs,
        pending=(),
    )

    plans_out: list[LabelledPlanOut] = []
    for lp in planset.plans:
        p_out = _build_plan_out(
            p=lp.plan,
            current_by_id=current_by_id,
            filler_ids=filler_ids,
            memberships=memberships,
            line_packs=line_packs,
            pending=lp.pending,
        )
        reasons_out = [
            ReasonOut(
                code=r.code,
                platform=r.platform,
                amount_paise=r.amount,
                line_ids=list(r.line_ids),
                text=r.text,
            )
            for r in lp.reasons
        ]
        plans_out.append(
            LabelledPlanOut(
                orders=p_out.orders,
                total_subtotal_paise=p_out.total_subtotal_paise,
                total_fees_paise=p_out.total_fees_paise,
                total_offer_value_paise=p_out.total_offer_value_paise,
                total_net_paise=p_out.total_net_paise,
                unpriced=p_out.unpriced,
                label=lp.label,
                effective_cost_paise=lp.effective_cost,
                savings_vs_baseline_paise=lp.savings_vs_baseline,
                reasons=reasons_out,
            )
        )

    return PlansResponse(baseline=baseline_out, plans=plans_out)


@router.post("/plans", response_model=PlansResponse)
def post_plans(
    req: PlansRequest,
    household_id: HouseholdIdDep,
    session: SessionDep,
    now_dt: ClockDep,
) -> PlansResponse:
    return run_plan(req, session=session, household_id=household_id, now_dt=now_dt)

