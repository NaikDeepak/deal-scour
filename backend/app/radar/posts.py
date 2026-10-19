import json
import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from urllib.parse import urlparse

from app.core.money import Paise

_URL_RE = re.compile(r"https?://[^\s<>\"\)\]\*]+", re.IGNORECASE)

# Match price expressions:
# 1. ₹99, ₹ 1,224*, ₹1,299.50
# 2. @828, @ ₹828, at 499, at ₹499, Rs. 599, INR 599 (not immediately followed by weight/count units)
# 3. bare number before " : http" or " : l1"
_PRICE_TOKEN_RE = re.compile(
    r"(?:"
    r"₹\s*(?P<rupee>[0-9][0-9,]*(?:\.[0-9]{1,2})?)\*?"
    r"|"
    r"(?:@|\bat|\brs\.?|\binr)\s*₹?\s*(?P<at>[0-9][0-9,]*(?:\.[0-9]{1,2})?)\*?(?!\s*(?:kg|kgs|g|gm|gms|ml|l|ltr|pcs|pc|pieces)\b)"
    r"|"
    r"(?:^|[\s/|,-])(?P<bare>[0-9][0-9,]*(?:\.[0-9]{1,2})?)\*?\s*:\s*(?=https?://|[A-Za-z0-9_.-]+)"
    r")",
    re.IGNORECASE | re.MULTILINE,
)

_SHORTHAND_PAIR_RE = re.compile(
    r"(?:^|[\s/|,-])(?P<price>[0-9][0-9,]*(?:\.[0-9]{1,2})?)\*?\s*:\s*(?P<link>[^\s/|]+)",
    re.MULTILINE,
)


@dataclass(frozen=True)
class PriceLinkPair:
    price_paise: Paise | None
    url: str


def normalize_peer_id(raw: str) -> str:
    """Normalize a Telegram Web URL or peer id string to a canonical peer_id (e.g. '-1001191090845')."""
    s = (raw or "").strip()
    if not s:
        raise ValueError("Channel peer_id cannot be empty")

    if s.startswith("http://") or s.startswith("https://"):
        parsed = urlparse(s)
        frag = (parsed.fragment or "").strip()
        if frag:
            s = frag.lstrip("#").strip()
            # Handle routes like ?tgaddr=... or k/#-100...
            if s.startswith("?"):
                raise ValueError(f"Could not extract channel id from Telegram URL: {raw}")
        else:
            path = parsed.path.strip("/")
            if path and parsed.hostname and "t.me" in parsed.hostname.lower():
                s = f"@{path.split('/')[-1]}"
            else:
                raise ValueError(f"Could not extract channel id from URL: {raw}")

    if s.startswith("#"):
        s = s[1:].strip()

    if not s or len(s) > 60 or not re.fullmatch(r"@?[A-Za-z0-9_-]+", s):
        raise ValueError(f"Invalid Telegram channel id: {raw!r}")
    return s


def _amount_to_paise(raw_num: str) -> Paise | None:
    cleaned = raw_num.replace(",", "").strip().rstrip("*")
    try:
        val = Decimal(cleaned)
    except InvalidOperation:
        return None
    if val <= 0:
        return None
    paise = int((val * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return paise if paise > 0 else None


def parse_price_paise(text: str) -> Paise | None:
    """Extract the first valid price in integer paise from a text fragment."""
    for m in _PRICE_TOKEN_RE.finditer(text or ""):
        raw = m.group("rupee") or m.group("at") or m.group("bare")
        if raw:
            paise = _amount_to_paise(raw)
            if paise is not None:
                return paise
    # Fallback if text is just a bare rupee string like "1,224*"
    m_plain = re.search(r"₹?\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)\*", text or "")
    if m_plain:
        return _amount_to_paise(m_plain.group(1))
    return None


def _clean_url(raw_url: str) -> str:
    return raw_url.rstrip(".,;:!?)>]*'\"")


def parse_post(text: str, extra_links: list[str] | None = None) -> list[PriceLinkPair]:
    """Parse a Telegram deal post into (price_paise, url) pairs.

    Pairs each link with the nearest price occurring before it.
    """
    body = (text or "")[:2000]

    # Collect price matches with their end positions
    price_positions: list[tuple[int, int, Paise]] = []
    for pm in _PRICE_TOKEN_RE.finditer(body):
        raw = pm.group("rupee") or pm.group("at") or pm.group("bare")
        if not raw:
            continue
        paise = _amount_to_paise(raw)
        if paise is not None:
            price_positions.append((pm.start(), pm.end(), paise))

    # Collect inline http/https URLs with their start positions
    url_matches: list[tuple[int, int, str]] = []
    for um in _URL_RE.finditer(body):
        cleaned = _clean_url(um.group(0))
        if cleaned:
            url_matches.append((um.start(), um.end(), cleaned))

    pairs: list[PriceLinkPair] = []
    seen_urls: set[str] = set()

    if url_matches:
        prev_url_end = 0
        for u_start, u_end, url in url_matches:
            # Find nearest price before u_start (preferring prices after prev_url_end)
            candidates_since_prev = [
                p for (p_start, p_end, p) in price_positions if prev_url_end <= p_start <= u_start
            ]
            if candidates_since_prev:
                matched_price: Paise | None = candidates_since_prev[-1]
            else:
                candidates_any_before = [p for (p_start, _, p) in price_positions if p_start <= u_start]
                matched_price = candidates_any_before[-1] if candidates_any_before else None

            pairs.append(PriceLinkPair(price_paise=matched_price, url=url))
            seen_urls.add(url)
            prev_url_end = u_end

    # If no inline http URLs were found, check shorthand "854 : l1" pairs mapped to extra_links
    if not pairs and extra_links:
        shorthand_prices = [p for (_, _, p) in price_positions]
        cleaned_extras = [_clean_url(u) for u in extra_links if u and _clean_url(u)]
        for idx, extra_url in enumerate(cleaned_extras):
            if extra_url in seen_urls:
                continue
            price_val = (
                shorthand_prices[idx]
                if idx < len(shorthand_prices)
                else (shorthand_prices[-1] if shorthand_prices else None)
            )
            pairs.append(PriceLinkPair(price_paise=price_val, url=extra_url))
            seen_urls.add(extra_url)
    elif extra_links:
        # Append any extra DOM links that weren't inline in text
        fallback_price = price_positions[-1][2] if price_positions else None
        for raw_extra in extra_links:
            cleaned_extra = _clean_url(raw_extra)
            if (
                cleaned_extra
                and cleaned_extra.startswith(("http://", "https://"))
                and cleaned_extra not in seen_urls
            ):
                pairs.append(PriceLinkPair(price_paise=fallback_price, url=cleaned_extra))
                seen_urls.add(cleaned_extra)

    # Also support bare shorthand tests like parse_post("854 : l1\n859 : l2") without extra_links
    if not pairs and not extra_links:
        for sm in _SHORTHAND_PAIR_RE.finditer(body):
            p_val = _amount_to_paise(sm.group("price"))
            link_tok = sm.group("link").strip()
            if p_val is not None and link_tok:
                pairs.append(PriceLinkPair(price_paise=p_val, url=link_tok))

    return pairs


def pairs_to_json(pairs: list[PriceLinkPair]) -> str:
    """Serialize parsed pairs so ingest can store them and the background job can resolve them later."""
    return json.dumps([{"price_paise": p.price_paise, "url": p.url} for p in pairs])


def pairs_from_json(raw: str) -> list[PriceLinkPair]:
    try:
        data = json.loads(raw or "[]")
    except ValueError:
        return []
    pairs: list[PriceLinkPair] = []
    if not isinstance(data, list):
        return pairs
    for entry in data:
        if not isinstance(entry, dict) or not isinstance(entry.get("url"), str):
            continue
        price = entry.get("price_paise")
        pairs.append(PriceLinkPair(price_paise=price if isinstance(price, int) else None, url=entry["url"]))
    return pairs
