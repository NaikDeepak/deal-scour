"""Background processing of pending Deal Radar posts: resolve -> verdict -> alert.

`POST /radar/posts` only stores posts as `pending`. `process_pending_posts` is called on a timer
(wired by the lead in `app/main.py`) and does all the slow work, so ingest never waits on the network.
"""

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Protocol

from sqlmodel import Session, col, select

from app.core.config import Settings, get_settings
from app.core.money import Paise
from app.domain.catalog import current_listings, rate_basis, to_utc
from app.domain.models import CustomListing, ListingWatch, PriceObservation, RadarKeyword, RadarPost
from app.notify.base import Notifier, record_and_dispatch_alert
from app.pricing.units import unit_rate
from app.radar.links import ResolvedLink
from app.radar.posts import pairs_from_json
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

logger = logging.getLogger(__name__)

PageFetcher = Callable[[str, str], LivePage | None]

# Which pair's verdict represents a post that links several products.
_VERDICT_PRIORITY = {
    "good": 5,
    "expired": 4,
    "skipped_budget": 3,
    "not_relevant": 2,
    "unsupported_link": 1,
}


class LinkResolving(Protocol):
    def resolve(self, raw_url: str) -> ResolvedLink: ...


def default_page_fetcher(platform: str, url: str) -> LivePage | None:
    """Fetch one Amazon/Flipkart product page through the shared fetcher lock and politeness gap."""
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


@dataclass(frozen=True)
class HouseholdRadarContext:
    tracked: dict[tuple[str, str], TrackedContext]
    keywords: set[str]
    tracked_families: set[str]
    family_best_rates: dict[str, FamilyRate]


def build_household_radar_context(
    session: Session,
    household_id: int,
    now_dt: datetime,
) -> HouseholdRadarContext:
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

    family_best_rates: dict[str, FamilyRate] = {}
    for cur in current_listings(session, household_id, now_dt):
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

    return HouseholdRadarContext(
        tracked=tracked_map,
        keywords=keywords,
        tracked_families=tracked_families,
        family_best_rates=family_best_rates,
    )


def untracked_fetches_used(session: Session, household_id: int, now: datetime) -> int:
    """Untracked page fetches stored on this household's posts in the last 24 h."""
    since = to_utc(now) - timedelta(hours=24)
    rows = session.exec(
        select(RadarPost.page_fetches, RadarPost.processed_at).where(
            RadarPost.household_id == household_id,
            col(RadarPost.page_fetches) > 0,
        )
    ).all()
    return sum(n for n, at in rows if at is not None and to_utc(at) >= since)


@dataclass
class _Budget:
    remaining: int
    used: int = 0

    def spend(self) -> None:
        self.remaining -= 1
        self.used += 1


@dataclass
class _PairResult:
    verdict: str
    reasons: list[str]
    platform: str | None = None
    sku: str | None = None
    listing_id: str | None = None
    url: str | None = None
    title: str | None = None
    pack_label: str | None = None
    family_key: str | None = None
    posted_paise: Paise | None = None
    live_paise: Paise | None = None


@dataclass
class _AlertCandidate:
    product_key: str
    platform: str
    sku: str
    title: str
    url: str
    price_paise: Paise
    reasons: list[str] = field(default_factory=list)


def _evaluate_post(
    session: Session,
    post: RadarPost,
    now: datetime,
    ctx: HouseholdRadarContext,
    budget: _Budget,
    resolver: LinkResolving,
    page_fetcher: PageFetcher,
) -> tuple[_PairResult, list[_AlertCandidate]]:
    best: _PairResult | None = None
    candidates: list[_AlertCandidate] = []

    for pair in pairs_from_json(post.pairs_json):
        resolved = resolver.resolve(pair.url)
        if resolved.status != "ok" or resolved.ref is None:
            result = _PairResult(
                verdict="unsupported_link",
                reasons=["unsupported_link"],
                posted_paise=pair.price_paise,
            )
        else:
            ref = resolved.ref
            tracked = ctx.tracked.get((ref.platform, ref.sku.upper()))

            def fetch(
                _platform: str = ref.platform,
                _url: str = ref.url,
                _tracked: TrackedContext | None = tracked,
            ) -> LivePage | None:
                if _tracked is None:
                    budget.spend()
                live = page_fetcher(_platform, _url)
                if live is not None and _tracked is not None:
                    mrp = live.mrp_paise if live.mrp_paise is not None else live.listed_paise
                    session.add(
                        PriceObservation(
                            household_id=post.household_id,
                            listing_id=_tracked.listing_id,
                            listed_paise=live.listed_paise,
                            mrp_paise=max(live.listed_paise, mrp),
                            in_stock=live.in_stock,
                            source="fetcher",
                            observed_at=now,
                        )
                    )
                    session.flush()
                return live

            outcome: VerdictOutcome = decide_verdict(
                post_text=post.text,
                posted_paise=pair.price_paise,
                platform=ref.platform,
                sku=ref.sku,
                tracked=tracked,
                keywords=ctx.keywords,
                tracked_families=ctx.tracked_families,
                family_best_rates=ctx.family_best_rates,
                fetch_page=fetch,
                final_url=resolved.final_url,
                untracked_fetch_allowed=budget.remaining > 0,
            )
            title = outcome.title or (tracked.title if tracked else None)
            result = _PairResult(
                verdict=outcome.verdict,
                reasons=outcome.reasons,
                platform=ref.platform,
                sku=ref.sku,
                listing_id=tracked.listing_id if tracked else None,
                url=ref.url,
                title=title,
                pack_label=outcome.pack_label or (tracked.pack_label if tracked else None),
                family_key=outcome.family_key or (tracked.family_key if tracked else None),
                posted_paise=outcome.posted_paise or pair.price_paise,
                live_paise=outcome.live_paise,
            )
            if outcome.verdict == "good":
                candidates.append(
                    _AlertCandidate(
                        product_key=f"{ref.platform}:{ref.sku.upper()}",
                        platform=ref.platform,
                        sku=ref.sku,
                        title=title or f"{ref.platform.title()} {ref.sku}",
                        url=ref.url,
                        price_paise=outcome.live_paise or outcome.posted_paise or pair.price_paise or 0,
                        reasons=outcome.reasons,
                    )
                )

        if best is None or _VERDICT_PRIORITY[result.verdict] > _VERDICT_PRIORITY[best.verdict]:
            best = result

    return best or _PairResult(verdict="not_relevant", reasons=["not_relevant"]), candidates


def _is_too_old(post: RadarPost, now: datetime, settings: Settings) -> bool:
    age = to_utc(now) - to_utc(post.posted_at)
    return age > timedelta(hours=settings.radar_max_post_age_hours)


def _finish(post: RadarPost, now: datetime, *, status: str, verdict: str, reasons: list[str]) -> None:
    post.status = status
    post.verdict = verdict
    post.reasons_json = json.dumps(reasons)
    post.processed_at = now


def _process_one(
    session: Session,
    post: RadarPost,
    now: datetime,
    settings: Settings,
    contexts: dict[int, HouseholdRadarContext],
    resolver: LinkResolving,
    page_fetcher: PageFetcher,
    notifier: Notifier,
) -> None:
    if _is_too_old(post, now, settings):
        _finish(post, now, status="too_old", verdict="too_old", reasons=["too_old"])
        session.add(post)
        session.commit()
        return

    ctx = contexts.get(post.household_id)
    if ctx is None:
        ctx = build_household_radar_context(session, post.household_id, now)
        contexts[post.household_id] = ctx

    budget = _Budget(
        remaining=max(
            0,
            settings.radar_max_page_fetches_per_day
            - untracked_fetches_used(session, post.household_id, now),
        )
    )
    best, candidates = _evaluate_post(session, post, now, ctx, budget, resolver, page_fetcher)

    _finish(post, now, status="done", verdict=best.verdict, reasons=best.reasons)
    post.platform = best.platform
    post.sku = best.sku
    post.listing_id = best.listing_id
    post.product_url = best.url
    post.title = best.title
    post.pack_label = best.pack_label
    post.family_key = best.family_key
    post.posted_paise = best.posted_paise
    post.live_paise = best.live_paise
    post.page_fetches = budget.used
    session.add(post)
    session.commit()
    session.refresh(post)

    for cand in candidates:
        record_and_dispatch_alert(
            session=session,
            household_id=post.household_id,
            now_dt=now,
            product_key=cand.product_key,
            platform=cand.platform,
            sku=cand.sku,
            title=cand.title,
            url=cand.url,
            price_paise=cand.price_paise,
            reasons=cand.reasons,
            notifier=notifier,
            post_id=post.id,
            quiet_start=settings.quiet_hours_start,
            quiet_end=settings.quiet_hours_end,
            daily_cap=settings.daily_alert_cap,
        )


def process_pending_posts(
    session: Session,
    now: datetime,
    *,
    resolver: LinkResolving,
    page_fetcher: PageFetcher,
    notifier: Notifier,
    limit: int = 10,
) -> int:
    """Process the oldest pending posts (resolve -> verdict -> alert); returns how many were finished.

    A post that raises is marked done as `not_relevant/processing_error` so it can never block the queue.
    """
    settings = get_settings()
    pending = session.exec(
        select(RadarPost)
        .where(RadarPost.status == "pending")
        .order_by(col(RadarPost.posted_at).asc(), col(RadarPost.id).asc())
        .limit(limit)
    ).all()

    contexts: dict[int, HouseholdRadarContext] = {}
    handled = 0
    for post in pending:
        post_id = post.id
        try:
            _process_one(session, post, now, settings, contexts, resolver, page_fetcher, notifier)
        except Exception:
            session.rollback()
            logger.exception("radar: processing post %s failed", post_id)
            failed = session.get(RadarPost, post_id) if post_id is not None else None
            if failed is not None:
                _finish(
                    failed,
                    now,
                    status="done",
                    verdict="not_relevant",
                    reasons=["processing_error"],
                )
                session.add(failed)
                session.commit()
        handled += 1
    return handled
