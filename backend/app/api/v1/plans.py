from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.core.money import Paise
from app.domain.catalog import SeedListing, load_seed
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

router = APIRouter()

_VALID_PLATFORMS: set[str] = {"amazon", "flipkart", "blinkit", "instamart", "zepto"}
ALL_PLATFORMS: list[Platform] = ["amazon", "flipkart", "blinkit", "instamart", "zepto"]


_DEFAULT_MEMBERS: list[Platform] = ["amazon", "instamart", "flipkart"]


class NeedIn(BaseModel):
    line_id: str
    product_key: str
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
    unit_price_paise: Paise
    qty: int
    is_filler: bool


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
    seed_by_id: dict[str, SeedListing],
    filler_ids: set[str],
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
            listing = seed_by_id[pline.listing_id]
            lines_out.append(
                OrderLineOut(
                    line_id=pline.line_id,
                    listing_id=pline.listing_id,
                    title=listing.title,
                    pack_label=listing.pack_label,
                    unit_price_paise=pline.unit_price,
                    qty=pline.qty,
                    is_filler=pline.line_id in filler_ids,
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


@router.post("/plans", response_model=PlansResponse)
def post_plans(req: PlansRequest) -> PlansResponse:
    # 1. Validate members
    members_set: set[Platform] = set()
    for m in req.members:
        if m not in _VALID_PLATFORMS:
            raise HTTPException(status_code=422, detail=f"Unknown platform in members: {m}")
        members_set.add(m)

    memberships: dict[Platform, bool] = {p: p in members_set for p in ALL_PLATFORMS}

    # Load seed data
    listings = load_seed()
    seed_by_id: dict[str, SeedListing] = {item.id: item for item in listings}
    seed_by_product: dict[str, list[SeedListing]] = {}
    for item in listings:
        seed_by_product.setdefault(item.product_key, []).append(item)

    # 2. Build needs
    seen_line_ids: set[str] = set()
    opt_needs: list[NeedLine] = []

    try:
        for need in req.needs:
            if need.qty < 1 or need.qty > 99:
                raise ValueError(f"qty must be 1..99, got {need.qty}")

            if need.line_id in seen_line_ids:
                raise ValueError(f"Duplicate line_id: {need.line_id}")
            seen_line_ids.add(need.line_id)

            if need.product_key not in seed_by_product:
                raise ValueError(f"Unknown product_key: {need.product_key}")

            prod_listings = seed_by_product[need.product_key]
            candidates = [
                Candidate(
                    listing_id=item.id,
                    platform=item.platform,
                    unit_price=unit_price(item.item_price(), memberships[item.platform]),
                    eta_minutes=item.eta_minutes,
                )
                for item in prod_listings
            ]

            opt_needs.append(
                NeedLine(
                    line_id=need.line_id,
                    category=prod_listings[0].category,
                    qty=need.qty,
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
            if f.filler_id in filler_ids:
                raise ValueError(f"Duplicate filler_id: {f.filler_id}")
            if f.filler_id in seen_line_ids:
                raise ValueError(f"filler_id '{f.filler_id}' conflicts with need line_id")
            filler_ids.add(f.filler_id)

            if f.listing_id not in seed_by_id:
                raise ValueError(f"Unknown filler listing_id: {f.listing_id}")
            listing = seed_by_id[f.listing_id]
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
        seed_by_id=seed_by_id,
        filler_ids=filler_ids,
        pending=(),
    )

    plans_out: list[LabelledPlanOut] = []
    for lp in planset.plans:
        p_out = _build_plan_out(
            p=lp.plan,
            seed_by_id=seed_by_id,
            filler_ids=filler_ids,
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


# HOOK: app.include_router(plans.router, prefix="/api/v1") in app/main.py (wired by lead)
