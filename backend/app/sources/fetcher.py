"""Polite price fetcher for Amazon and Flipkart custom listings (ADR-004)."""

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urljoin, urlsplit

from sqlalchemy.engine import Engine
from sqlmodel import Session, col, select

from app.core.config import Settings
from app.domain.catalog import to_utc
from app.domain.models import CustomListing, Household, PriceObservation, SourceStatus
from app.sources.pages import PageBlockedError, PageParseError, parse_amazon_product, parse_flipkart_product

logger = logging.getLogger(__name__)

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
)


@dataclass
class RefreshReport:
    fetched: int = 0
    updated: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)
    skipped_platforms: list[str] = field(default_factory=list)


# Only these hosts are ever requested, including after redirects (no SSRF via a redirect).
ALLOWED_FETCH_HOSTS = frozenset({"www.amazon.in", "amazon.in", "www.flipkart.com", "flipkart.com"})
MAX_REDIRECTS = 3
MAX_BODY_BYTES = 6 * 1024 * 1024


class FetchRefusedError(Exception):
    """Redirect to a host we don't fetch, non-https, or an oversized page."""


def _check_url(url: str) -> None:
    parts = urlsplit(url)
    if parts.scheme != "https" or (parts.hostname or "").lower() not in ALLOWED_FETCH_HOSTS:
        raise FetchRefusedError(f"refusing to fetch {parts.scheme}://{parts.hostname}")


def fetch_url(url: str) -> tuple[int, str]:
    import httpx

    headers = {
        "User-Agent": DEFAULT_USER_AGENT,
        "Accept-Language": "en-IN,en;q=0.9",
    }
    with httpx.Client(timeout=15.0, headers=headers, follow_redirects=False) as client:
        for _ in range(MAX_REDIRECTS + 1):
            _check_url(url)
            with client.stream("GET", url) as resp:
                if resp.is_redirect:
                    url = urljoin(url, resp.headers.get("location", ""))
                    continue
                body = bytearray()
                for chunk in resp.iter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_BODY_BYTES:
                        raise FetchRefusedError("page larger than 6 MB")
                return resp.status_code, body.decode(resp.encoding or "utf-8", errors="replace")
        raise FetchRefusedError("too many redirects")


def _handle_platform_failure(
    session: Session,
    platform: str,
    reason: str,
    now: Callable[[], datetime],
    report: RefreshReport,
    listing_id: str,
) -> None:
    short_reason = reason[:200]
    report.failed.append((listing_id, short_reason))
    st = session.get(SourceStatus, platform)
    if not st:
        st = SourceStatus(platform=platform)
    st.consecutive_failures += 1
    st.last_error = short_reason
    if st.consecutive_failures >= 3:
        st.disabled_until = now() + timedelta(hours=24)
        if platform not in report.skipped_platforms:
            report.skipped_platforms.append(platform)
    session.add(st)
    session.commit()


def get_due_listings(
    session: Session,
    household_id: int,
    *,
    now_dt: datetime,
    interval_hours: int,
    limit: int = 30,
) -> list[CustomListing]:
    """Find non-archived amazon/flipkart custom listings due for refresh, oldest first, max limit."""
    candidate_listings = session.exec(
        select(CustomListing).where(
            CustomListing.household_id == household_id,
            CustomListing.archived.is_(False),  # type: ignore[attr-defined]
            col(CustomListing.platform).in_(["amazon", "flipkart"]),
        )
    ).all()

    # Get latest fetcher observation for each listing
    observations = session.exec(
        select(PriceObservation).where(
            PriceObservation.household_id == household_id,
            PriceObservation.source == "fetcher",
        )
    ).all()
    latest_fetcher_obs: dict[str, PriceObservation] = {}
    for obs in observations:
        prev = latest_fetcher_obs.get(obs.listing_id)
        if prev is None or to_utc(obs.observed_at) > to_utc(prev.observed_at):
            latest_fetcher_obs[obs.listing_id] = obs

    threshold = to_utc(now_dt) - timedelta(hours=interval_hours)
    due: list[tuple[datetime, datetime, int, CustomListing]] = []

    for cl in candidate_listings:
        latest_obs = latest_fetcher_obs.get(cl.listing_id)
        if latest_obs is None:
            # Never fetched: effective observation time is minimum datetime
            due.append((datetime.min.replace(tzinfo=UTC), to_utc(cl.created_at), cl.id or 0, cl))
        elif to_utc(latest_obs.observed_at) <= threshold:
            due.append((to_utc(latest_obs.observed_at), to_utc(cl.created_at), cl.id or 0, cl))

    # Sort oldest first (oldest observation first, ties broken by created_at, then id)
    due.sort(key=lambda t: (t[0], t[1], t[2]))
    return [item[3] for item in due[:limit]]


# One fetch run at a time per process (background loop, manual refresh, every household), so requests to a
# site are always sequential and spaced, never parallel.
_RUN_LOCK = threading.Lock()


def refresh_due_listings(
    session: Session,
    household_id: int,
    *,
    http_get: Callable[[str], tuple[int, str]],
    now: Callable[[], datetime],
    sleep: Callable[[float], None],
    interval_hours: int,
) -> RefreshReport:
    with _RUN_LOCK:
        report = _refresh_due_listings(
            session, household_id, http_get=http_get, now=now, sleep=sleep, interval_hours=interval_hours
        )
        if report.fetched:
            sleep(10.0)  # keep the 10 s gap to whichever run takes the lock next
        return report


def _refresh_due_listings(
    session: Session,
    household_id: int,
    *,
    http_get: Callable[[str], tuple[int, str]],
    now: Callable[[], datetime],
    sleep: Callable[[float], None],
    interval_hours: int,
) -> RefreshReport:
    report = RefreshReport()
    now_dt = now()

    # Per-platform gate at start
    for platform in ("amazon", "flipkart"):
        st = session.get(SourceStatus, platform)
        if (
            st
            and st.disabled_until
            and to_utc(st.disabled_until) > to_utc(now_dt)
            and platform not in report.skipped_platforms
        ):
            report.skipped_platforms.append(platform)

    due_listings = get_due_listings(
        session,
        household_id,
        now_dt=now_dt,
        interval_hours=interval_hours,
        limit=30,
    )

    last_fetched_platform_time: dict[str, datetime] = {}

    for listing in due_listings:
        if listing.platform in report.skipped_platforms:
            continue

        # Check if platform became disabled during this run
        st = session.get(SourceStatus, listing.platform)
        if st and st.disabled_until and to_utc(st.disabled_until) > to_utc(now()):
            if listing.platform not in report.skipped_platforms:
                report.skipped_platforms.append(listing.platform)
            continue

        # Politeness: at least 10s between requests to the same platform
        if listing.platform in last_fetched_platform_time:
            prev_time = last_fetched_platform_time[listing.platform]
            gap = (to_utc(now()) - to_utc(prev_time)).total_seconds()
            if gap < 10.0:
                sleep(10.0 - gap)
        last_fetched_platform_time[listing.platform] = now()

        report.fetched += 1

        try:
            status_code, body = http_get(listing.url)
        except Exception as exc:
            _handle_platform_failure(
                session,
                listing.platform,
                f"network: {type(exc).__name__}: {str(exc)[:100]}",
                now,
                report,
                listing.listing_id,
            )
            continue

        if status_code != 200:
            _handle_platform_failure(
                session,
                listing.platform,
                f"HTTP {status_code}",
                now,
                report,
                listing.listing_id,
            )
            continue

        try:
            if listing.platform == "amazon":
                parsed = parse_amazon_product(body)
            elif listing.platform == "flipkart":
                parsed = parse_flipkart_product(body)
            else:
                continue
        except PageBlockedError as exc:
            _handle_platform_failure(
                session,
                listing.platform,
                f"blocked: {exc}",
                now,
                report,
                listing.listing_id,
            )
            continue
        except PageParseError as exc:
            report.failed.append((listing.listing_id, f"parse: {exc}"[:200]))
            continue

        # Calculate MRP with fallback
        if parsed.mrp_paise is not None:
            obs_mrp = parsed.mrp_paise
        else:
            prev_obs = session.exec(
                select(PriceObservation)
                .where(
                    PriceObservation.household_id == household_id,
                    PriceObservation.listing_id == listing.listing_id,
                )
                .order_by(col(PriceObservation.observed_at).desc())
            ).first()
            prev_mrp = prev_obs.mrp_paise if prev_obs is not None else parsed.listed_paise
            obs_mrp = max(parsed.listed_paise, prev_mrp)

        obs = PriceObservation(
            household_id=household_id,
            listing_id=listing.listing_id,
            listed_paise=parsed.listed_paise,
            mrp_paise=obs_mrp,
            in_stock=parsed.in_stock,
            source="fetcher",
            observed_at=now(),
        )
        session.add(obs)

        # Success resets consecutive_failures to 0
        st = session.get(SourceStatus, listing.platform)
        if not st:
            st = SourceStatus(platform=listing.platform)
        st.consecutive_failures = 0
        st.last_success_at = now()
        st.last_error = None
        session.add(st)
        session.commit()

        report.updated.append(listing.listing_id)

    return report


_LOOP_STARTED = threading.Event()


def setup_fetcher_loop(app: Any, settings: Settings, engine: Engine | None = None) -> Any:
    """Start the single background fetch loop when DEALSCOUR_FETCHERS=1. Returns the stop event (or None)."""
    if not settings.fetchers_enabled:
        return None
    app.state.fetcher_loop_registered = True
    if engine is None or _LOOP_STARTED.is_set():
        return None
    _LOOP_STARTED.set()
    stop = threading.Event()
    threading.Thread(
        target=run_fetcher_worker,
        args=(engine, settings.fetch_interval_hours, stop),
        name="dealscour-fetcher",
        daemon=True,
    ).start()
    logger.info(
        "Price fetcher enabled: Amazon + Flipkart custom listings every %sh", settings.fetch_interval_hours
    )
    return stop


def run_fetcher_worker(
    engine: Engine,
    interval_hours: int,
    stop_event: threading.Event,
    *,
    initial_delay: float = 60.0,
    http_get: Callable[[str], tuple[int, str]] = fetch_url,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    logger.info("Starting price fetcher worker loop")
    if stop_event.wait(timeout=initial_delay):
        return
    while not stop_event.is_set():
        try:
            with Session(engine) as session:
                households = session.exec(select(Household.id)).all()
                for hh_id in households:
                    if hh_id is None or stop_event.is_set():
                        continue
                    try:
                        refresh_due_listings(
                            session,
                            hh_id,
                            http_get=http_get,
                            now=now,
                            sleep=sleep,
                            interval_hours=interval_hours,
                        )
                    except Exception:
                        logger.exception("Error refreshing listings for household %s", hh_id)
        except Exception:
            logger.exception("Unexpected error in fetcher background loop")
        if stop_event.wait(timeout=interval_hours * 3600):
            break
