"""Pure verdict evaluation for Deal Radar (Section C)."""

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from app.core.money import Paise
from app.domain.catalog import rate_basis
from app.pricing.units import Unit, parse_pack, unit_rate
from app.sources.autofill import _extract_family_and_category, _extract_pack_label

VerdictStatus = Literal["good", "expired", "not_relevant", "unsupported_link"]

_GENERIC_POST_WORDS = frozenset(
    {
        "loot",
        "deal",
        "deals",
        "offer",
        "offers",
        "steal",
        "price",
        "drop",
        "fast",
        "grab",
        "now",
        "buy",
        "link",
        "apply",
        "coupon",
        "code",
        "off",
        "flat",
        "rs",
        "inr",
        "at",
        "mrp",
        "only",
        "from",
        "amazon",
        "flipkart",
    }
)


@dataclass(frozen=True)
class TrackedContext:
    listing_id: str
    platform: str
    sku: str
    title: str
    pack_label: str
    category: str
    family_key: str
    target_paise: Paise | None = None
    obs_30d_paise: list[Paise] = field(default_factory=list)


@dataclass(frozen=True)
class FamilyRate:
    family_key: str
    category: str
    best_unit_rate_paise: Paise
    unit: Unit


@dataclass(frozen=True)
class LivePage:
    listed_paise: Paise
    mrp_paise: Paise | None = None
    in_stock: bool = True
    title: str | None = None
    pack_label: str | None = None


@dataclass(frozen=True)
class VerdictOutcome:
    verdict: VerdictStatus
    reasons: list[str]
    title: str | None = None
    pack_label: str | None = None
    family_key: str | None = None
    posted_paise: Paise | None = None
    live_paise: Paise | None = None
    live_mrp_paise: Paise | None = None
    live_in_stock: bool | None = None


def _has_meaningful_product_hint(post_text: str) -> str:
    """Strip URLs, prices, numbers, and generic deal buzzwords to see if post names a product."""
    without_urls = re.sub(r"https?://\S+", " ", post_text or "")
    without_prices = re.sub(
        r"(?:₹|@|\brs\.?|\binr)\s*[0-9][0-9,]*(?:\.[0-9]+)?\*?",
        " ",
        without_urls,
        flags=re.I,
    )
    words = re.findall(r"[A-Za-z]{3,}", without_prices.lower())
    meaningful = [w for w in words if w not in _GENERIC_POST_WORDS]
    return " ".join(meaningful)


def _matches_keywords_or_families(
    text: str,
    keywords: set[str],
    tracked_families: set[str],
) -> tuple[bool, str | None, str | None]:
    """Check if text matches any household RadarKeyword or tracked family_key."""
    lower = (text or "").lower()
    if not lower.strip():
        return False, None, None

    extracted_fam, extracted_cat = _extract_family_and_category(lower)

    matched_kw = False
    for kw in keywords:
        kw_clean = kw.strip().lower()
        if kw_clean and re.search(rf"\b{re.escape(kw_clean)}\b", lower):
            matched_kw = True
            break

    matched_fam: str | None = None
    if extracted_fam and (extracted_fam in tracked_families or matched_kw):
        matched_fam = extracted_fam
    else:
        for fam in tracked_families:
            fam_words = fam.replace("_", " ").strip().lower()
            if fam_words and re.search(rf"\b{re.escape(fam_words)}\b", lower):
                matched_fam = fam
                break

    if matched_kw or matched_fam is not None:
        return True, (matched_fam or extracted_fam), (extracted_cat or "staples")
    return False, None, None


def _verify_live_page(
    effective_posted_paise: Paise,
    live: LivePage,
    reasons: list[str],
    title: str | None,
    pack_label: str | None,
    family_key: str | None,
) -> VerdictOutcome:
    """Rule 8: live page price must be <= posted price + 5% and in stock. Otherwise expired."""
    if not live.in_stock or (live.listed_paise * 100 > effective_posted_paise * 105):
        return VerdictOutcome(
            verdict="expired",
            reasons=["expired"],
            title=live.title or title,
            pack_label=pack_label,
            family_key=family_key,
            posted_paise=effective_posted_paise,
            live_paise=live.listed_paise,
            live_mrp_paise=live.mrp_paise,
            live_in_stock=live.in_stock,
        )
    return VerdictOutcome(
        verdict="good",
        reasons=reasons,
        title=live.title or title,
        pack_label=pack_label,
        family_key=family_key,
        posted_paise=effective_posted_paise,
        live_paise=live.listed_paise,
        live_mrp_paise=live.mrp_paise,
        live_in_stock=live.in_stock,
    )


def decide_verdict(
    *,
    post_text: str,
    posted_paise: Paise | None,
    platform: str,
    sku: str,
    tracked: TrackedContext | None,
    keywords: set[str],
    tracked_families: set[str],
    family_best_rates: dict[str, FamilyRate],
    fetch_page: Callable[[], LivePage | None] | None = None,
) -> VerdictOutcome:
    """Pure decision function for a resolved product link in a Telegram post."""
    # 1. Tracked product (Rule 6)
    if tracked is not None:
        candidate_price = posted_paise
        live_page: LivePage | None = None

        if candidate_price is None and fetch_page is not None:
            live_page = fetch_page()
            if live_page is not None:
                candidate_price = live_page.listed_paise

        if candidate_price is None or candidate_price <= 0:
            return VerdictOutcome(
                verdict="not_relevant",
                reasons=["not_relevant"],
                title=tracked.title,
                pack_label=tracked.pack_label,
                family_key=tracked.family_key,
            )

        reasons: list[str] = []
        if tracked.target_paise is not None and candidate_price <= tracked.target_paise:
            reasons.append("below_target")

        if len(tracked.obs_30d_paise) >= 3:
            low_30d = min(tracked.obs_30d_paise)
            if candidate_price <= low_30d:
                reasons.append("30d_low")

        if tracked.obs_30d_paise:
            avg_30d = (
                sum(tracked.obs_30d_paise) + len(tracked.obs_30d_paise) // 2
            ) // len(tracked.obs_30d_paise)
            if avg_30d > 0 and (candidate_price * 100 <= avg_30d * 85):
                reasons.append("under_avg")

        if not reasons:
            return VerdictOutcome(
                verdict="not_relevant",
                reasons=["not_relevant"],
                title=tracked.title,
                pack_label=tracked.pack_label,
                family_key=tracked.family_key,
                posted_paise=candidate_price,
            )

        if live_page is None and fetch_page is not None:
            live_page = fetch_page()

        if live_page is None:
            return VerdictOutcome(
                verdict="expired",
                reasons=["expired"],
                title=tracked.title,
                pack_label=tracked.pack_label,
                family_key=tracked.family_key,
                posted_paise=candidate_price,
            )

        return _verify_live_page(
            effective_posted_paise=candidate_price,
            live=live_page,
            reasons=reasons,
            title=tracked.title,
            pack_label=tracked.pack_label,
            family_key=tracked.family_key,
        )

    # 2. Untracked product (Rule 7)
    if platform not in ("amazon", "flipkart"):
        return VerdictOutcome(verdict="not_relevant", reasons=["not_relevant"])

    # Pre-fetch relevance check: if the post text clearly describes a product (e.g. "Luggage")
    # and does NOT match any keyword or tracked family, skip fetching the page!
    hint_words = _has_meaningful_product_hint(post_text)
    if hint_words:
        matched_hint, _, _ = _matches_keywords_or_families(post_text, keywords, tracked_families)
        if not matched_hint:
            return VerdictOutcome(
                verdict="not_relevant",
                reasons=["not_relevant"],
                posted_paise=posted_paise,
            )

    if fetch_page is None:
        return VerdictOutcome(
            verdict="not_relevant",
            reasons=["not_relevant"],
            posted_paise=posted_paise,
        )

    live_page = fetch_page()
    if live_page is None:
        return VerdictOutcome(
            verdict="expired",
            reasons=["expired"],
            posted_paise=posted_paise,
        )

    combined_title = live_page.title or post_text
    is_cand, family_key, category = _matches_keywords_or_families(
        combined_title, keywords, tracked_families
    )
    if not is_cand or not family_key:
        return VerdictOutcome(
            verdict="not_relevant",
            reasons=["not_relevant"],
            title=live_page.title,
            posted_paise=posted_paise,
            live_paise=live_page.listed_paise,
            live_mrp_paise=live_page.mrp_paise,
            live_in_stock=live_page.in_stock,
        )

    pack_label = (
        live_page.pack_label
        or _extract_pack_label(live_page.title or "")
        or _extract_pack_label(post_text)
    )
    if not pack_label:
        return VerdictOutcome(
            verdict="not_relevant",
            reasons=["not_relevant"],
            title=live_page.title,
            family_key=family_key,
            posted_paise=posted_paise,
            live_paise=live_page.listed_paise,
            live_mrp_paise=live_page.mrp_paise,
            live_in_stock=live_page.in_stock,
        )

    try:
        pack = parse_pack(pack_label)
    except ValueError:
        return VerdictOutcome(
            verdict="not_relevant",
            reasons=["not_relevant"],
            title=live_page.title,
            pack_label=pack_label,
            family_key=family_key,
            posted_paise=posted_paise,
            live_paise=live_page.listed_paise,
            live_mrp_paise=live_page.mrp_paise,
            live_in_stock=live_page.in_stock,
        )

    fam_rate = family_best_rates.get(family_key)
    if fam_rate is None or fam_rate.unit != pack.unit or fam_rate.best_unit_rate_paise <= 0:
        return VerdictOutcome(
            verdict="not_relevant",
            reasons=["not_relevant"],
            title=live_page.title,
            pack_label=pack_label,
            family_key=family_key,
            posted_paise=posted_paise,
            live_paise=live_page.listed_paise,
            live_mrp_paise=live_page.mrp_paise,
            live_in_stock=live_page.in_stock,
        )

    effective_posted = posted_paise if posted_paise is not None else live_page.listed_paise
    basis_qty, _ = rate_basis(fam_rate.category or category or "staples", pack.unit)
    cand_unit_rate = unit_rate(effective_posted, pack, basis_qty)

    # Rule 7: GOOD if unit price is >= 10% below best current unit price in that family
    if cand_unit_rate * 100 > fam_rate.best_unit_rate_paise * 90:
        return VerdictOutcome(
            verdict="not_relevant",
            reasons=["not_relevant"],
            title=live_page.title,
            pack_label=pack_label,
            family_key=family_key,
            posted_paise=effective_posted,
            live_paise=live_page.listed_paise,
            live_mrp_paise=live_page.mrp_paise,
            live_in_stock=live_page.in_stock,
        )

    return _verify_live_page(
        effective_posted_paise=effective_posted,
        live=live_page,
        reasons=["beats_family_best"],
        title=live_page.title,
        pack_label=pack_label,
        family_key=family_key,
    )
