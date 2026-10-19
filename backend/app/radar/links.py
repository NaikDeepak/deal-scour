import re
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from urllib.parse import parse_qs, urljoin, urlparse

from app.domain.catalog import to_utc
from app.sources.fetcher import DEFAULT_USER_AGENT
from app.sources.urls import ProductRef, parse_product_url

SHORT_LINK_HOSTS = frozenset(
    {
        "amzn.to",
        "www.amzn.to",
        "link.amazon",
        "www.link.amazon",
        "amzn.in",
        "www.amzn.in",
        "fkrt.it",
        "www.fkrt.it",
        "fkrt.cc",
        "www.fkrt.cc",
    }
)

PRODUCT_HOSTS = frozenset(
    {
        "amazon.in",
        "www.amazon.in",
        "m.amazon.in",
        "flipkart.com",
        "www.flipkart.com",
        "dl.flipkart.com",
    }
)

MAX_HOPS = 4
MAX_SHORT_BODY_BYTES = 256 * 1024
MIN_RESOLUTION_GAP_SECONDS = 2.0
MAX_RESOLUTIONS_PER_HOUR = 120
CACHE_TTL_DAYS = 7


@dataclass(frozen=True)
class ResolvedLink:
    status: Literal["ok", "unsupported", "rate_limited"]
    ref: ProductRef | None = None
    reason: str = "ok"
    # Last hop URL before canonicalisation. Its path slug names the product ("/Tata-Sampann-Almonds-500g/dp/…"),
    # which the relevance gate reads before any page is fetched.
    final_url: str | None = None


def _is_short_link(url: str) -> bool:
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return False
    if parsed.scheme.lower() != "https":
        return False
    host = (parsed.hostname or "").lower()
    if host in SHORT_LINK_HOSTS:
        return True
    return host == "dl.flipkart.com" and parsed.path.startswith("/s/")


def _is_allowed_hop_url(url: str) -> bool:
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return False
    if parsed.scheme.lower() != "https":
        return False
    host = (parsed.hostname or "").lower()
    return host in SHORT_LINK_HOSTS or host in PRODUCT_HOSTS


def _try_parse_direct_product(url: str) -> ProductRef | None:
    """Attempt to canonicalize a direct Amazon/Flipkart product URL without network access."""
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return None
    if parsed.scheme.lower() != "https":
        return None
    host = (parsed.hostname or "").lower()
    if host not in PRODUCT_HOSTS:
        return None
    if host == "dl.flipkart.com" and parsed.path.startswith("/s/"):
        return None

    try:
        ref = parse_product_url(url)
        if ref.platform in ("amazon", "flipkart"):
            return ref
    except ValueError:
        pass

    # Handle Amazon URLs with extra path segments around /dp/{ASIN} or /gp/product/{ASIN}
    if host in ("amazon.in", "www.amazon.in", "m.amazon.in"):
        m = re.search(r"/(?:dp|gp/product|gp/aw/d)/([A-Za-z0-9]{10})(?:[/?#]|$)", parsed.path)
        if m:
            asin = m.group(1).upper()
            try:
                return parse_product_url(f"https://www.amazon.in/dp/{asin}")
            except ValueError:
                return None

    # Handle Flipkart URLs where slug might have unusual characters or be omitted before /p/itm...
    if host in ("flipkart.com", "www.flipkart.com", "dl.flipkart.com"):
        m_itm = re.search(r"(?:/([^/]+))?/p/(itm[A-Za-z0-9]{6,20})", parsed.path, re.IGNORECASE)
        qs = parse_qs(parsed.query)
        pids = qs.get("pid")
        if m_itm and pids and pids[0]:
            raw_slug = m_itm.group(1) or "product"
            slug = re.sub(r"[^a-z0-9-]+", "-", raw_slug.lower()).strip("-") or "product"
            itm = m_itm.group(2).lower()
            pid = pids[0].upper()
            try:
                return parse_product_url(f"https://www.flipkart.com/{slug}/p/{itm}?pid={pid}")
            except ValueError:
                return None

    return None


def _default_http_fetch(url: str, max_bytes: int) -> tuple[int, dict[str, str], bytes]:
    import httpx

    headers = {
        "User-Agent": DEFAULT_USER_AGENT,
        "Accept-Language": "en-IN,en;q=0.9",
    }
    with (
        httpx.Client(timeout=10.0, headers=headers, follow_redirects=False) as client,
        client.stream("GET", url) as resp,
    ):
        resp_headers = {k.lower(): v for k, v in resp.headers.items()}
        if resp.is_redirect or "location" in resp_headers:
            return resp.status_code, resp_headers, b""
        body = bytearray()
        for chunk in resp.iter_bytes():
            body.extend(chunk)
            if len(body) > max_bytes:
                raise ValueError("Response body exceeds 256 KB limit")
        return resp.status_code, resp_headers, bytes(body)


class LinkResolver:
    """Resolves allow-listed short links. Safe to share across threads (the radar loop and requests)."""

    def __init__(
        self,
        *,
        http_fetch: Callable[[str, int], tuple[int, dict[str, str], bytes]] = _default_http_fetch,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._http_fetch = http_fetch
        self._now = now
        self._sleep = sleep
        self._lock = threading.Lock()
        self._cache: dict[str, tuple[ResolvedLink, datetime]] = {}
        self._recent_resolutions: deque[datetime] = deque()
        self._last_resolution_at: datetime | None = None

    def _enforce_politeness(self) -> bool:
        # Held while sleeping on purpose: concurrent callers queue up, which is what "≤ 1 per 2 s" means.
        with self._lock:
            now_dt = to_utc(self._now())
            one_hour_ago = now_dt - timedelta(hours=1)
            while self._recent_resolutions and self._recent_resolutions[0] <= one_hour_ago:
                self._recent_resolutions.popleft()

            if len(self._recent_resolutions) >= MAX_RESOLUTIONS_PER_HOUR:
                return False

            if self._last_resolution_at is not None:
                elapsed = (now_dt - self._last_resolution_at).total_seconds()
                if elapsed < MIN_RESOLUTION_GAP_SECONDS:
                    self._sleep(MIN_RESOLUTION_GAP_SECONDS - elapsed)
                    now_dt = to_utc(self._now())

            self._last_resolution_at = now_dt
            self._recent_resolutions.append(now_dt)
            return True

    def _cached(self, url: str) -> ResolvedLink | None:
        with self._lock:
            cached = self._cache.get(url)
            if cached is None:
                return None
            cached_res, cached_at = cached
            if (to_utc(self._now()) - to_utc(cached_at)) < timedelta(days=CACHE_TTL_DAYS):
                return cached_res
            return None

    def _remember(self, url: str, res: ResolvedLink) -> ResolvedLink:
        with self._lock:
            self._cache[url] = (res, to_utc(self._now()))
        return res

    def resolve(self, raw_url: str) -> ResolvedLink:
        url = (raw_url or "").strip()
        if not url:
            return ResolvedLink(status="unsupported", ref=None, reason="unsupported_link")

        # 1. Check if it is already a direct Amazon/Flipkart product URL
        direct = _try_parse_direct_product(url)
        if direct is not None:
            return ResolvedLink(status="ok", ref=direct, reason="ok", final_url=url)

        # 2. Otherwise it must be on the short-link allow-list
        if not _is_short_link(url):
            return ResolvedLink(status="unsupported", ref=None, reason="unsupported_link")

        cached = self._cached(url)
        if cached is not None:
            return cached

        if not self._enforce_politeness():
            return ResolvedLink(status="rate_limited", ref=None, reason="unsupported_link")

        unsupported = ResolvedLink(status="unsupported", ref=None, reason="unsupported_link")
        current_url = url
        for hop in range(MAX_HOPS + 1):
            if not _is_allowed_hop_url(current_url):
                return self._remember(url, unsupported)

            parsed_ref = _try_parse_direct_product(current_url)
            if parsed_ref is not None:
                return self._remember(
                    url,
                    ResolvedLink(status="ok", ref=parsed_ref, reason="ok", final_url=current_url),
                )

            if hop == MAX_HOPS:
                break

            try:
                status_code, headers, _body = self._http_fetch(current_url, MAX_SHORT_BODY_BYTES)
            except Exception:
                return unsupported

            location = headers.get("location") or headers.get("Location")
            if status_code in (301, 302, 303, 307, 308) and location:
                current_url = urljoin(current_url, location.strip())
                continue
            break

        return self._remember(url, unsupported)


_DEFAULT_RESOLVER = LinkResolver()


def resolve_link(url: str) -> ResolvedLink:
    return _DEFAULT_RESOLVER.resolve(url)
