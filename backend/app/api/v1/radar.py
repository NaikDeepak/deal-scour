import json
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlmodel import Session, col, select

from app.core import clock
from app.core.config import get_settings
from app.core.db import current_household_id, current_user, get_session
from app.core.extension_auth import (
    ExtensionHouseholdIdDep,
    issue_extension_token,
    verify_extension_bearer_token,
)
from app.core.money import Paise
from app.domain.catalog import current_listings, rate_basis, to_utc
from app.domain.models import (
    CustomListing,
    ListingWatch,
    PriceObservation,
    RadarAlert,
    RadarChannel,
    RadarKeyword,
    RadarPost,
)
from app.notify.base import Notifier, record_and_dispatch_alert
from app.notify.telegram import TelegramNotifier
from app.pricing.units import unit_rate
from app.radar.links import _DEFAULT_RESOLVER, LinkResolver
from app.radar.posts import normalize_peer_id, parse_post
from app.radar.verdict import (
    FamilyRate,
    LivePage,
    TrackedContext,
    VerdictOutcome,
    decide_verdict,
)
from app.sources import autofill
from app.sources.fetcher import _RUN_LOCK, fetch_url
from app.sources.pages import parse_amazon_product, parse_flipkart_product

router = APIRouter()

HouseholdIdDep = Annotated[int, Depends(current_household_id)]
SessionDep = Annotated[Session, Depends(get_session)]
ClockDep = Annotated[datetime, Depends(clock.now)]


def get_notifier() -> Notifier:
    settings = get_settings()
    return TelegramNotifier(
        bot_token=settings.telegram_bot_token,
        chat_id=settings.telegram_chat_id,
    )


def get_resolver() -> LinkResolver:
    return _DEFAULT_RESOLVER


def _default_page_fetcher(platform: str, url: str) -> LivePage | None:
    if platform not in ("amazon", "flipkart"):
        return None
    if not _RUN_LOCK.acquire(timeout=autofill._LOCK_TIMEOUT):
        return None
    try:
        elapsed = autofill._clock_monotonic() - autofill._LAST_FETCH_TIME[0]
        if elapsed < 10.0:
            autofill._sleep(10.0 - elapsed)
        status_code, body = fetch_url(url)
        autofill._LAST_FETCH_TIME[0] = autofill._clock_monotonic()
    except Exception:
        return None
    finally:
        _RUN_LOCK.release()

    if status_code != 200:
        return None

    try:
        parsed = parse_amazon_product(body) if platform == "amazon" else parse_flipkart_product(body)
    except Exception:
        return None

    return LivePage(
        listed_paise=parsed.listed_paise,
        mrp_paise=parsed.mrp_paise,
        in_stock=parsed.in_stock,
        title=parsed.title,
    )


def get_page_fetcher() -> Callable[[str, str], LivePage | None]:
    return _default_page_fetcher


NotifierDep = Annotated[Notifier, Depends(get_notifier)]
ResolverDep = Annotated[LinkResolver, Depends(get_resolver)]
PageFetcherDep = Annotated[Callable[[str, str], LivePage | None], Depends(get_page_fetcher)]


def _session_or_bearer_household_id(
    request: Request,
    session: SessionDep,
    now_dt: ClockDep,
) -> int:
    """Allow GET /radar/channels via Bearer token (extension) or session cookie (web portal)."""
    auth_header = request.headers.get("Authorization")
    if auth_header:
        return verify_extension_bearer_token(auth_header, session, now_dt)
    user = current_user(request=request, session=session, now_dt=now_dt)
    return current_household_id(user=user, session=session, _csrf=None)


SessionOrBearerHouseholdDep = Annotated[int, Depends(_session_or_bearer_household_id)]


class ExtensionTokenResponse(BaseModel):
    token: str
    created_at: datetime


class RadarChannelOut(BaseModel):
    id: int
    peer_id: str
    name: str
    enabled: bool
    created_at: datetime


class RadarChannelsResponse(BaseModel):
    channels: list[RadarChannelOut]
    peer_ids: list[str]


class CreateChannelRequest(BaseModel):
    peer_id: str
    name: str = Field(min_length=1, max_length=120)
    enabled: bool = True


class UpdateChannelRequest(BaseModel):
    enabled: bool | None = None
    name: str | None = Field(default=None, min_length=1, max_length=120)


class RadarKeywordOut(BaseModel):
    id: int
    keyword: str
    created_at: datetime


class RadarKeywordsResponse(BaseModel):
    keywords: list[RadarKeywordOut]


class CreateKeywordRequest(BaseModel):
    keyword: str = Field(min_length=1, max_length=80)


class IngestPostItem(BaseModel):
    peer_id: str = Field(min_length=1, max_length=120)
    message_id: str = Field(min_length=1, max_length=80)
    text: str = ""
    links: list[str] = Field(default_factory=list)
    posted_at: datetime | None = None


class IngestPostsRequest(BaseModel):
    posts: list[IngestPostItem]


class RadarPostOut(BaseModel):
    id: int
    peer_id: str
    message_id: str
    text: str
    posted_at: datetime
    verdict: str
    reasons: list[str]
    platform: str | None = None
    sku: str | None = None
    listing_id: str | None = None
    product_url: str | None = None
    title: str | None = None
    pack_label: str | None = None
    family_key: str | None = None
    posted_paise: Paise | None = None
    live_paise: Paise | None = None
    created_at: datetime


class IngestPostsResponse(BaseModel):
    processed: int
    ignored: int
    deduped: int
    alerts_created: int
    posts: list[RadarPostOut]


class RadarPostsResponse(BaseModel):
    posts: list[RadarPostOut]


class RadarAlertOut(BaseModel):
    id: int
    title: str
    price_paise: Paise
    reasons: list[str]
    url: str
    platform: str
    sku: str
    created_at: datetime


class RadarAlertsResponse(BaseModel):
    alerts: list[RadarAlertOut]


class TestAlertResponse(BaseModel):
    ok: bool
    telegram_sent: bool
    alert_id: int | None = None


def _post_to_out(row: RadarPost) -> RadarPostOut:
    try:
        reasons = json.loads(row.reasons_json)
        if not isinstance(reasons, list):
            reasons = []
    except Exception:
        reasons = []
    assert row.id is not None
    return RadarPostOut(
        id=row.id,
        peer_id=row.peer_id,
        message_id=row.message_id,
        text=row.text,
        posted_at=row.posted_at,
        verdict=row.verdict,
        reasons=[str(r) for r in reasons],
        platform=row.platform,
        sku=row.sku,
        listing_id=row.listing_id,
        product_url=row.product_url,
        title=row.title,
        pack_label=row.pack_label,
        family_key=row.family_key,
        posted_paise=row.posted_paise,
        live_paise=row.live_paise,
        created_at=row.created_at,
    )


@router.post("/radar/extension-token", response_model=ExtensionTokenResponse)
def create_extension_token_endpoint(
    household_id: HouseholdIdDep,
    session: SessionDep,
    now_dt: ClockDep,
) -> ExtensionTokenResponse:
    raw_token, row = issue_extension_token(session, household_id, now_dt)
    return ExtensionTokenResponse(token=raw_token, created_at=row.created_at)


@router.get("/radar/channels", response_model=RadarChannelsResponse)
def list_radar_channels(
    household_id: SessionOrBearerHouseholdDep,
    session: SessionDep,
) -> RadarChannelsResponse:
    rows = session.exec(
        select(RadarChannel)
        .where(RadarChannel.household_id == household_id)
        .order_by(col(RadarChannel.id).asc())
    ).all()
    channels = [
        RadarChannelOut(
            id=r.id or 0,
            peer_id=r.peer_id,
            name=r.name,
            enabled=r.enabled,
            created_at=r.created_at,
        )
        for r in rows
    ]
    peer_ids = [r.peer_id for r in rows if r.enabled]
    return RadarChannelsResponse(channels=channels, peer_ids=peer_ids)


@router.post("/radar/channels", response_model=RadarChannelOut)
def create_radar_channel(
    req: CreateChannelRequest,
    household_id: HouseholdIdDep,
    session: SessionDep,
    now_dt: ClockDep,
) -> RadarChannelOut:
    try:
        peer_id = normalize_peer_id(req.peer_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    name = req.name.strip()
    if not name:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Channel name is required",
        )

    existing = session.exec(
        select(RadarChannel).where(
            RadarChannel.household_id == household_id,
            RadarChannel.peer_id == peer_id,
        )
    ).first()
    if existing is not None:
        existing.name = name
        existing.enabled = req.enabled
        session.add(existing)
        session.commit()
        session.refresh(existing)
        assert existing.id is not None
        return RadarChannelOut(
            id=existing.id,
            peer_id=existing.peer_id,
            name=existing.name,
            enabled=existing.enabled,
            created_at=existing.created_at,
        )

    channel = RadarChannel(
        household_id=household_id,
        peer_id=peer_id,
        name=name,
        enabled=req.enabled,
        created_at=now_dt,
    )
    session.add(channel)
    session.commit()
    session.refresh(channel)
    assert channel.id is not None
    return RadarChannelOut(
        id=channel.id,
        peer_id=channel.peer_id,
        name=channel.name,
        enabled=channel.enabled,
        created_at=channel.created_at,
    )


@router.patch("/radar/channels/{channel_id}", response_model=RadarChannelOut)
def update_radar_channel(
    channel_id: int,
    req: UpdateChannelRequest,
    household_id: HouseholdIdDep,
    session: SessionDep,
) -> RadarChannelOut:
    channel = session.exec(
        select(RadarChannel).where(
            RadarChannel.id == channel_id,
            RadarChannel.household_id == household_id,
        )
    ).first()
    if channel is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Channel not found")

    if req.enabled is not None:
        channel.enabled = req.enabled
    if req.name is not None:
        channel.name = req.name.strip()
    session.add(channel)
    session.commit()
    session.refresh(channel)
    assert channel.id is not None
    return RadarChannelOut(
        id=channel.id,
        peer_id=channel.peer_id,
        name=channel.name,
        enabled=channel.enabled,
        created_at=channel.created_at,
    )


@router.delete("/radar/channels/{channel_id}")
def delete_radar_channel(
    channel_id: int,
    household_id: HouseholdIdDep,
    session: SessionDep,
) -> dict[str, bool]:
    channel = session.exec(
        select(RadarChannel).where(
            RadarChannel.id == channel_id,
            RadarChannel.household_id == household_id,
        )
    ).first()
    if channel is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Channel not found")
    session.delete(channel)
    session.commit()
    return {"deleted": True}


@router.get("/radar/keywords", response_model=RadarKeywordsResponse)
def list_radar_keywords(
    household_id: HouseholdIdDep,
    session: SessionDep,
) -> RadarKeywordsResponse:
    rows = session.exec(
        select(RadarKeyword)
        .where(RadarKeyword.household_id == household_id)
        .order_by(col(RadarKeyword.id).asc())
    ).all()
    return RadarKeywordsResponse(
        keywords=[
            RadarKeywordOut(id=r.id or 0, keyword=r.keyword, created_at=r.created_at)
            for r in rows
        ]
    )


@router.post("/radar/keywords", response_model=RadarKeywordOut)
def create_radar_keyword(
    req: CreateKeywordRequest,
    household_id: HouseholdIdDep,
    session: SessionDep,
    now_dt: ClockDep,
) -> RadarKeywordOut:
    kw = req.keyword.strip().lower()
    if not kw or len(kw) > 80:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid keyword")

    existing = session.exec(
        select(RadarKeyword).where(
            RadarKeyword.household_id == household_id,
            RadarKeyword.keyword == kw,
        )
    ).first()
    if existing is not None:
        assert existing.id is not None
        return RadarKeywordOut(id=existing.id, keyword=existing.keyword, created_at=existing.created_at)

    row = RadarKeyword(household_id=household_id, keyword=kw, created_at=now_dt)
    session.add(row)
    session.commit()
    session.refresh(row)
    assert row.id is not None
    return RadarKeywordOut(id=row.id, keyword=row.keyword, created_at=row.created_at)


@router.delete("/radar/keywords/{keyword_id}")
def delete_radar_keyword(
    keyword_id: int,
    household_id: HouseholdIdDep,
    session: SessionDep,
) -> dict[str, bool]:
    row = session.exec(
        select(RadarKeyword).where(
            RadarKeyword.id == keyword_id,
            RadarKeyword.household_id == household_id,
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Keyword not found")
    session.delete(row)
    session.commit()
    return {"deleted": True}


def _build_household_radar_context(
    session: Session,
    household_id: int,
    now_dt: datetime,
) -> tuple[
    dict[tuple[str, str], TrackedContext],
    set[str],
    set[str],
    dict[str, FamilyRate],
]:
    """Gather tracked listings, keywords, tracked families, and best current unit rates per family."""
    custom_rows = session.exec(
        select(CustomListing).where(
            CustomListing.household_id == household_id,
            CustomListing.archived.is_(False),  # type: ignore[attr-defined]
        )
    ).all()

    watches = session.exec(
        select(ListingWatch).where(ListingWatch.household_id == household_id)
    ).all()
    watch_by_listing = {w.listing_id: w for w in watches}

    since_30d = to_utc(now_dt) - timedelta(days=30)
    all_obs = session.exec(
        select(PriceObservation).where(
            PriceObservation.household_id == household_id,
            PriceObservation.source != "sample",
        )
    ).all()
    obs_30d_by_listing: dict[str, list[Paise]] = {}
    for o in all_obs:
        if to_utc(o.observed_at) >= since_30d:
            obs_30d_by_listing.setdefault(o.listing_id, []).append(o.listed_paise)

    tracked_map: dict[tuple[str, str], TrackedContext] = {}
    tracked_families: set[str] = set()

    for cl in custom_rows:
        tracked_families.add(cl.family_key)
        w = watch_by_listing.get(cl.listing_id)
        tracked_map[(cl.platform, cl.sku.upper())] = TrackedContext(
            listing_id=cl.listing_id,
            platform=cl.platform,
            sku=cl.sku,
            title=cl.title,
            pack_label=cl.pack_label,
            category=cl.category,
            family_key=cl.family_key,
            target_paise=w.target_paise if w else None,
            obs_30d_paise=obs_30d_by_listing.get(cl.listing_id, []),
        )

    kw_rows = session.exec(
        select(RadarKeyword).where(RadarKeyword.household_id == household_id)
    ).all()
    keywords = {k.keyword.strip().lower() for k in kw_rows if k.keyword.strip()}

    curr_all = current_listings(session, household_id, now_dt)
    family_best_rates: dict[str, FamilyRate] = {}
    for cur in curr_all:
        if cur.listing.id in watch_by_listing:
            tracked_families.add(cur.listing.family_key)
        if not cur.in_stock or cur.freshness not in ("fresh", "ok") or cur.source == "sample":
            continue
        pack = cur.listing.pack
        basis_qty, _ = rate_basis(cur.listing.category, pack.unit)
        ur = unit_rate(cur.listing.listed, pack, basis_qty)
        fam = cur.listing.family_key
        prev = family_best_rates.get(fam)
        if prev is None or ur < prev.best_unit_rate_paise:
            family_best_rates[fam] = FamilyRate(
                family_key=fam,
                category=cur.listing.category,
                best_unit_rate_paise=ur,
                unit=pack.unit,
            )

    return tracked_map, keywords, tracked_families, family_best_rates


_VERDICT_PRIORITY = {
    "good": 4,
    "expired": 3,
    "not_relevant": 2,
    "unsupported_link": 1,
}


@router.post("/radar/posts", response_model=IngestPostsResponse)
def ingest_radar_posts(
    req: IngestPostsRequest,
    household_id: ExtensionHouseholdIdDep,
    session: SessionDep,
    now_dt: ClockDep,
    notifier: NotifierDep,
    resolver: ResolverDep,
    page_fetcher: PageFetcherDep,
) -> IngestPostsResponse:
    if len(req.posts) > 50:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Batch size cannot exceed 50 posts",
        )

    settings = get_settings()
    enabled_channels = session.exec(
        select(RadarChannel).where(
            RadarChannel.household_id == household_id,
            col(RadarChannel.enabled).is_(True),
        )
    ).all()
    allowed_peers = {c.peer_id for c in enabled_channels}

    tracked_map, keywords, tracked_families, family_best_rates = _build_household_radar_context(
        session, household_id, now_dt
    )

    processed = 0
    ignored = 0
    deduped = 0
    alerts_created = 0
    out_posts: list[RadarPostOut] = []

    for item in req.posts:
        try:
            peer_id = normalize_peer_id(item.peer_id)
        except ValueError:
            ignored += 1
            continue

        if peer_id not in allowed_peers:
            ignored += 1
            continue

        msg_id = item.message_id.strip()
        if not msg_id:
            ignored += 1
            continue

        existing = session.exec(
            select(RadarPost).where(
                RadarPost.household_id == household_id,
                RadarPost.peer_id == peer_id,
                RadarPost.message_id == msg_id,
            )
        ).first()
        if existing is not None:
            deduped += 1
            continue

        truncated_text = (item.text or "")[:2000]
        pairs = parse_post(truncated_text, extra_links=item.links)

        best_verdict = "not_relevant"
        best_reasons: list[str] = ["not_relevant"]
        best_platform: str | None = None
        best_sku: str | None = None
        best_listing_id: str | None = None
        best_url: str | None = None
        best_title: str | None = None
        best_pack: str | None = None
        best_family: str | None = None
        best_posted_paise: Paise | None = None
        best_live_paise: Paise | None = None

        good_candidates_for_alert: list[tuple[str, str, str, str, Paise, list[str]]] = []

        for pair in pairs:
            resolved = resolver.resolve(pair.url)
            if resolved.status != "ok" or resolved.ref is None:
                if _VERDICT_PRIORITY["unsupported_link"] > _VERDICT_PRIORITY.get(best_verdict, 0) or (
                    best_verdict == "not_relevant" and best_url is None
                ):
                    best_verdict = "unsupported_link"
                    best_reasons = ["unsupported_link"]
                    best_posted_paise = pair.price_paise
                continue

            ref = resolved.ref
            tracked = tracked_map.get((ref.platform, ref.sku.upper()))

            def _fetch_and_record(
                _plat: str = ref.platform,
                _url: str = ref.url,
                _tracked: TrackedContext | None = tracked,
            ) -> LivePage | None:
                live = page_fetcher(_plat, _url)
                if live is not None and _tracked is not None:
                    obs_mrp = live.mrp_paise if live.mrp_paise is not None else live.listed_paise
                    obs = PriceObservation(
                        household_id=household_id,
                        listing_id=_tracked.listing_id,
                        listed_paise=live.listed_paise,
                        mrp_paise=max(live.listed_paise, obs_mrp),
                        in_stock=live.in_stock,
                        source="fetcher",
                        observed_at=now_dt,
                    )
                    session.add(obs)
                    session.flush()
                return live

            outcome: VerdictOutcome = decide_verdict(
                post_text=truncated_text,
                posted_paise=pair.price_paise,
                platform=ref.platform,
                sku=ref.sku,
                tracked=tracked,
                keywords=keywords,
                tracked_families=tracked_families,
                family_best_rates=family_best_rates,
                fetch_page=_fetch_and_record,
            )

            if _VERDICT_PRIORITY[outcome.verdict] >= _VERDICT_PRIORITY.get(best_verdict, 0):
                best_verdict = outcome.verdict
                best_reasons = outcome.reasons
                best_platform = ref.platform
                best_sku = ref.sku
                best_listing_id = tracked.listing_id if tracked else None
                best_url = ref.url
                best_title = outcome.title or (tracked.title if tracked else None)
                best_pack = outcome.pack_label or (tracked.pack_label if tracked else None)
                best_family = outcome.family_key or (tracked.family_key if tracked else None)
                best_posted_paise = outcome.posted_paise or pair.price_paise
                best_live_paise = outcome.live_paise

            if outcome.verdict == "good":
                alert_price = outcome.live_paise or outcome.posted_paise or pair.price_paise or 0
                alert_title = outcome.title or (
                    tracked.title if tracked else f"{ref.platform.title()} {ref.sku}"
                )
                prod_key = f"{ref.platform}:{ref.sku.upper()}"
                good_candidates_for_alert.append(
                    (prod_key, ref.platform, ref.sku, alert_title, alert_price, outcome.reasons)
                )
                # Store canonical URL alongside
                best_url = ref.url

        post_row = RadarPost(
            household_id=household_id,
            peer_id=peer_id,
            message_id=msg_id,
            text=truncated_text,
            posted_at=item.posted_at or now_dt,
            verdict=best_verdict,
            reasons_json=json.dumps(best_reasons),
            platform=best_platform,
            sku=best_sku,
            listing_id=best_listing_id,
            product_url=best_url,
            title=best_title,
            pack_label=best_pack,
            family_key=best_family,
            posted_paise=best_posted_paise,
            live_paise=best_live_paise,
            created_at=now_dt,
        )
        session.add(post_row)
        session.commit()
        session.refresh(post_row)

        for prod_key, plat, sku, alert_title, alert_price, reasons in good_candidates_for_alert:
            alert_url = best_url or f"https://www.amazon.in/dp/{sku}"
            alert_row = record_and_dispatch_alert(
                session=session,
                household_id=household_id,
                now_dt=now_dt,
                product_key=prod_key,
                platform=plat,
                sku=sku,
                title=alert_title,
                url=alert_url,
                price_paise=alert_price,
                reasons=reasons,
                notifier=notifier,
                post_id=post_row.id,
                quiet_start=settings.quiet_hours_start,
                quiet_end=settings.quiet_hours_end,
                daily_cap=settings.daily_alert_cap,
            )
            if alert_row is not None:
                alerts_created += 1

        processed += 1
        out_posts.append(_post_to_out(post_row))

    return IngestPostsResponse(
        processed=processed,
        ignored=ignored,
        deduped=deduped,
        alerts_created=alerts_created,
        posts=out_posts,
    )


@router.get("/radar/posts", response_model=RadarPostsResponse)
def list_radar_posts(
    household_id: HouseholdIdDep,
    session: SessionDep,
    verdict: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
) -> RadarPostsResponse:
    stmt = select(RadarPost).where(RadarPost.household_id == household_id)
    if verdict:
        stmt = stmt.where(RadarPost.verdict == verdict)
    stmt = stmt.order_by(col(RadarPost.id).desc()).limit(limit)
    rows = session.exec(stmt).all()
    return RadarPostsResponse(posts=[_post_to_out(r) for r in rows])


@router.get("/radar/alerts", response_model=RadarAlertsResponse)
def get_radar_alerts(
    household_id: ExtensionHouseholdIdDep,
    session: SessionDep,
    since: str | None = Query(default=None),
) -> RadarAlertsResponse:
    rows = session.exec(
        select(RadarAlert)
        .where(RadarAlert.household_id == household_id)
        .order_by(col(RadarAlert.id).asc())
    ).all()

    since_dt: datetime | None = None
    since_id: int | None = None
    if since:
        s_clean = since.strip()
        if s_clean.isdigit():
            since_id = int(s_clean)
        else:
            try:
                since_dt = to_utc(datetime.fromisoformat(s_clean.replace("Z", "+00:00")))
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Invalid since parameter",
                ) from None

    filtered: list[RadarAlertOut] = []
    for r in rows:
        assert r.id is not None
        if since_id is not None and r.id <= since_id:
            continue
        if since_dt is not None and to_utc(r.created_at) <= since_dt:
            continue
        try:
            reasons = json.loads(r.reasons_json)
            if not isinstance(reasons, list):
                reasons = []
        except Exception:
            reasons = []
        filtered.append(
            RadarAlertOut(
                id=r.id,
                title=r.title,
                price_paise=r.price_paise,
                reasons=[str(x) for x in reasons],
                url=r.url,
                platform=r.platform,
                sku=r.sku,
                created_at=r.created_at,
            )
        )

    return RadarAlertsResponse(alerts=filtered)


@router.post("/radar/test-alert", response_model=TestAlertResponse)
def send_test_radar_alert(
    household_id: HouseholdIdDep,
    session: SessionDep,
    now_dt: ClockDep,
    notifier: NotifierDep,
) -> TestAlertResponse:
    settings = get_settings()
    alert = record_and_dispatch_alert(
        session=session,
        household_id=household_id,
        now_dt=now_dt,
        product_key=f"test:B072HG4WNC:{int(now_dt.timestamp())}",
        platform="amazon",
        sku="B072HG4WNC",
        title="Test Deal Alert (Tata Sampann Toor Dal 1kg)",
        url="https://www.amazon.in/dp/B072HG4WNC",
        price_paise=14900,
        reasons=["below_target"],
        notifier=notifier,
        quiet_start=settings.quiet_hours_start,
        quiet_end=settings.quiet_hours_end,
        daily_cap=settings.daily_alert_cap,
    )
    if alert is None:
        return TestAlertResponse(ok=False, telegram_sent=False, alert_id=None)
    return TestAlertResponse(
        ok=True,
        telegram_sent=(alert.telegram_status == "sent"),
        alert_id=alert.id,
    )
