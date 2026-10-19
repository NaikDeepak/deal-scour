from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlmodel import Session, select

from app.domain.models import RadarAlert
from app.notify.base import (
    AlertPayload,
    record_and_dispatch_alert,
    send_due_alerts,
)
from app.notify.telegram import TelegramNotifier
from app.radar.links import LinkResolver
from app.radar.posts import PriceLinkPair, normalize_peer_id, parse_post, parse_price_paise
from app.radar.verdict import (
    FamilyRate,
    LivePage,
    TrackedContext,
    decide_verdict,
)

FIXED_NOW = datetime(2026, 10, 19, 12, 0, 0, tzinfo=UTC)


# Case 1: Parse "Loot ₹99 : https://amzn.to/x", "854 : l1\n859 : l2",
# "Pampers 42 pcs @828 https://link.amazon/y", "₹1,224*" -> right (price, link) pairs.
def test_case_1_parse_posts_price_and_link_pairs() -> None:
    # 1a. "Loot ₹99 : https://amzn.to/x"
    pairs_1 = parse_post("Loot ₹99 : https://amzn.to/x")
    assert pairs_1 == [PriceLinkPair(price_paise=9900, url="https://amzn.to/x")]

    # 1b. "854 : l1\n859 : l2" with two links
    l1 = "https://amzn.to/item1"
    l2 = "https://fkrt.it/item2"
    pairs_2 = parse_post(f"854 : {l1}\n859 : {l2}")
    assert pairs_2 == [
        PriceLinkPair(price_paise=85400, url=l1),
        PriceLinkPair(price_paise=85900, url=l2),
    ]
    # Also support slash-separated and shorthand with extra_links
    pairs_2_slash = parse_post(f"854 : {l1} / 859 : {l2}")
    assert pairs_2_slash == [
        PriceLinkPair(price_paise=85400, url=l1),
        PriceLinkPair(price_paise=85900, url=l2),
    ]
    pairs_2_shorthand = parse_post("854 : l1\n859 : l2", extra_links=[l1, l2])
    assert pairs_2_shorthand == [
        PriceLinkPair(price_paise=85400, url=l1),
        PriceLinkPair(price_paise=85900, url=l2),
    ]

    # 1c. "Pampers 42 pcs @828 https://link.amazon/y" -> 42 pcs is NOT the price, @828 is
    pairs_3 = parse_post("Pampers 42 pcs @828 https://link.amazon/y")
    assert pairs_3 == [PriceLinkPair(price_paise=82800, url="https://link.amazon/y")]

    # 1d. "₹1,224*" and "at 499"
    assert parse_price_paise("₹1,224*") == 122400
    pairs_4 = parse_post("Optimum Nutrition ₹1,224* https://amzn.in/d/abc123")
    assert pairs_4 == [PriceLinkPair(price_paise=122400, url="https://amzn.in/d/abc123")]

    pairs_5 = parse_post("Almonds 500g at 399 https://dl.flipkart.com/s/xyz")
    assert pairs_5 == [PriceLinkPair(price_paise=39900, url="https://dl.flipkart.com/s/xyz")]


def test_normalize_peer_id() -> None:
    assert normalize_peer_id("https://web.telegram.org/k/#-1001191090845") == "-1001191090845"
    assert normalize_peer_id("https://web.telegram.org/a/#-1001191090845") == "-1001191090845"
    assert normalize_peer_id("#-1001191090845") == "-1001191090845"
    assert normalize_peer_id("  -1001191090845  ") == "-1001191090845"


# Case 2: Resolve amzn.to -> amazon.in/dp/ASIN?tag=... -> canonical without tag.
# A hop to a non-allowed host -> unsupported. myntr.it -> unsupported.
def test_case_2_resolve_short_and_direct_links_and_politeness() -> None:
    now_box = [FIXED_NOW]
    slept: list[float] = []
    hop_calls: list[str] = []

    routes: dict[str, tuple[int, dict[str, str], bytes]] = {
        "https://amzn.to/x": (
            301,
            {"location": "https://www.amazon.in/Tata-Sampann-Dal/dp/B072HG4WNC?tag=offerbox-21&psc=1"},
            b"",
        ),
        "https://fkrt.cc/badhop": (
            302,
            {"location": "https://evil.example.com/track?u=1"},
            b"",
        ),
        "https://dl.flipkart.com/s/fk1": (
            302,
            {
                "location": (
                    "https://www.flipkart.com/happilo-almonds/p/itm123456"
                    "?pid=JASHRN6FZUFHMESG&affid=offerbox"
                )
            },
            b"",
        ),
        "https://link.amazon/loop1": (302, {"location": "https://amzn.in/loop2"}, b""),
        "https://amzn.in/loop2": (302, {"location": "https://amzn.to/loop3"}, b""),
        "https://amzn.to/loop3": (302, {"location": "https://link.amazon/loop4"}, b""),
        "https://link.amazon/loop4": (302, {"location": "https://amzn.in/loop5"}, b""),
        "https://amzn.in/loop5": (
            302,
            {"location": "https://www.amazon.in/dp/B072HG4WNC"},
            b"",
        ),
    }

    def fake_http(url: str, max_bytes: int) -> tuple[int, dict[str, str], bytes]:
        assert max_bytes <= 256 * 1024
        hop_calls.append(url)
        if url not in routes:
            return (404, {}, b"")
        return routes[url]

    def fake_sleep(seconds: float) -> None:
        slept.append(seconds)
        now_box[0] = now_box[0] + timedelta(seconds=seconds)

    resolver = LinkResolver(
        http_fetch=fake_http,
        now=lambda: now_box[0],
        sleep=fake_sleep,
    )

    # 2a. Direct product link drops affiliate tag without HTTP call
    direct = resolver.resolve("https://www.amazon.in/dp/B072HG4WNC?tag=affiliate-21&th=1")
    assert direct.status == "ok"
    assert direct.ref is not None
    assert direct.ref.platform == "amazon"
    assert direct.ref.sku == "B072HG4WNC"
    assert direct.ref.url == "https://www.amazon.in/dp/B072HG4WNC"
    assert "tag=" not in direct.ref.url
    assert len(hop_calls) == 0

    # 2b. amzn.to -> amazon.in/dp/ASIN?tag=... -> canonical without tag
    res_amzn = resolver.resolve("https://amzn.to/x")
    assert res_amzn.status == "ok"
    assert res_amzn.ref is not None
    assert res_amzn.ref.url == "https://www.amazon.in/dp/B072HG4WNC"
    assert res_amzn.ref.sku == "B072HG4WNC"
    assert len(hop_calls) == 1

    # 2c. Cached for 7 days -> second call makes no HTTP request and doesn't sleep
    now_box[0] = now_box[0] + timedelta(days=6)
    res_cached = resolver.resolve("https://amzn.to/x")
    assert res_cached.status == "ok"
    assert len(hop_calls) == 1

    # 2d. Hop to non-allowed host -> unsupported
    res_bad_hop = resolver.resolve("https://fkrt.cc/badhop")
    assert res_bad_hop.status == "unsupported"
    assert res_bad_hop.ref is None

    # 2e. myntr.it, clnk.in, bit.ly -> unsupported without any HTTP call
    calls_before = len(hop_calls)
    for blocked in ("https://myntr.it/abc", "https://clnk.in/xyz", "https://bit.ly/123"):
        r = resolver.resolve(blocked)
        assert r.status == "unsupported"
        assert r.ref is None
    assert len(hop_calls) == calls_before

    # 2f. Politeness: <= 1 resolution per 2s (resolving immediately after fkrt.cc sleeps ~2s)
    res_fk = resolver.resolve("https://dl.flipkart.com/s/fk1")
    assert res_fk.status == "ok"
    assert res_fk.ref is not None
    assert res_fk.ref.url == "https://www.flipkart.com/happilo-almonds/p/itm123456?pid=JASHRN6FZUFHMESG"
    assert any(s > 0 for s in slept)

    # 2g. More than 4 hops -> unsupported
    res_too_many = resolver.resolve("https://link.amazon/loop1")
    assert res_too_many.status == "unsupported"


# Case 3: Tracked butter at ₹290 with target ₹300 -> GOOD below_target.
# ₹330 with 30-day low ₹300 -> not_relevant.
def test_case_3_tracked_product_verdicts() -> None:
    tracked_butter = TrackedContext(
        listing_id="cus-1",
        platform="amazon",
        sku="B0BUTTER01",
        title="Amul Butter 500g",
        pack_label="500g",
        category="dairy",
        family_key="butter",
        target_paise=30000,
        obs_30d_paise=[31000, 30500, 30000],
    )

    # 3a. Tracked butter at ₹290 with target ₹300 -> GOOD below_target
    v_good = decide_verdict(
        post_text="Amul Butter 500g ₹290 : https://amzn.to/b",
        posted_paise=29000,
        platform="amazon",
        sku="B0BUTTER01",
        tracked=tracked_butter,
        keywords=set(),
        tracked_families={"butter"},
        family_best_rates={},
        fetch_page=lambda: LivePage(
            listed_paise=29000, mrp_paise=32000, in_stock=True, title="Amul Butter 500g"
        ),
    )
    assert v_good.verdict == "good"
    assert "below_target" in v_good.reasons

    # 3b. ₹330 with 30-day low ₹300 (and no target hit) -> not_relevant, no page fetch
    fetch_called = False

    def fail_if_called() -> LivePage:
        nonlocal fetch_called
        fetch_called = True
        return LivePage(listed_paise=33000, in_stock=True)

    tracked_no_target = TrackedContext(
        listing_id="cus-1",
        platform="amazon",
        sku="B0BUTTER01",
        title="Amul Butter 500g",
        pack_label="500g",
        category="dairy",
        family_key="butter",
        target_paise=None,
        obs_30d_paise=[30000, 31000, 32000],
    )
    v_irrelevant = decide_verdict(
        post_text="Amul Butter 500g ₹330 : https://amzn.to/b",
        posted_paise=33000,
        platform="amazon",
        sku="B0BUTTER01",
        tracked=tracked_no_target,
        keywords=set(),
        tracked_families={"butter"},
        family_best_rates={},
        fetch_page=fail_if_called,
    )
    assert v_irrelevant.verdict == "not_relevant"
    assert v_irrelevant.reasons == ["not_relevant"]
    assert fetch_called is False

    # 3c. Tracked item hitting 30d_low (>= 3 obs) and under_avg (>= 15% under 30d avg)
    tracked_hist = TrackedContext(
        listing_id="cus-2",
        platform="amazon",
        sku="B0GHEE0001",
        title="Amul Cow Ghee 1L",
        pack_label="1L",
        category="dairy",
        family_key="ghee",
        target_paise=None,
        obs_30d_paise=[60000, 62000, 58000],  # avg = 60000, low = 58000
    )
    v_low_and_avg = decide_verdict(
        post_text="Amul Ghee 1L ₹500 : https://amzn.to/g",
        posted_paise=50000,  # <= 58000 (30d_low) and <= 60000 * 0.85 = 51000 (under_avg)
        platform="amazon",
        sku="B0GHEE0001",
        tracked=tracked_hist,
        keywords=set(),
        tracked_families={"ghee"},
        family_best_rates={},
        fetch_page=lambda: LivePage(
            listed_paise=50000, mrp_paise=65000, in_stock=True, title="Amul Cow Ghee 1L"
        ),
    )
    assert v_low_and_avg.verdict == "good"
    assert "30d_low" in v_low_and_avg.reasons
    assert "under_avg" in v_low_and_avg.reasons


# Case 4: Untracked whey (keyword "whey") 1kg at ₹2,400 when family best is ₹2,899/kg
# -> GOOD beats_family_best. Luggage -> not_relevant, no page fetch.
def test_case_4_untracked_product_verdicts_and_no_fetch_for_luggage() -> None:
    family_rates = {
        "whey_protein": FamilyRate(
            family_key="whey_protein", category="fitness", best_unit_rate_paise=289900, unit="g"
        ),
    }

    # 4a. Untracked whey 1kg at ₹2,400 vs family best ₹2,899/kg -> GOOD beats_family_best
    whey_fetches = 0

    def fetch_whey() -> LivePage:
        nonlocal whey_fetches
        whey_fetches += 1
        return LivePage(
            listed_paise=240000,
            mrp_paise=329900,
            in_stock=True,
            title="Optimum Nutrition Gold Standard 100% Whey Protein Powder 1kg",
        )

    v_whey = decide_verdict(
        post_text="Optimum Nutrition Whey 1kg ₹2,400 : https://amzn.to/whey",
        posted_paise=240000,
        platform="amazon",
        sku="B0WHEY1000",
        tracked=None,
        keywords={"whey", "peanut butter", "almonds"},
        tracked_families={"whey_protein", "butter"},
        family_best_rates=family_rates,
        fetch_page=fetch_whey,
    )
    assert v_whey.verdict == "good"
    assert v_whey.reasons == ["beats_family_best"]
    assert whey_fetches == 1

    # 4b. Luggage -> not_relevant, NO page fetch!
    luggage_fetches = 0

    def fetch_luggage() -> LivePage:
        nonlocal luggage_fetches
        luggage_fetches += 1
        return LivePage(
            listed_paise=199900,
            mrp_paise=599900,
            in_stock=True,
            title="Safari Pentagon 55cm Cabin Luggage Trolley Bag",
        )

    v_luggage = decide_verdict(
        post_text="Safari Pentagon 55cm Cabin Luggage ₹1,999 : https://amzn.to/lug",
        posted_paise=199900,
        platform="amazon",
        sku="B0LUGGAGE1",
        tracked=None,
        keywords={"whey", "peanut butter", "almonds"},
        tracked_families={"whey_protein", "butter"},
        family_best_rates=family_rates,
        fetch_page=fetch_luggage,
    )
    assert v_luggage.verdict == "not_relevant"
    assert v_luggage.reasons == ["not_relevant"]
    assert luggage_fetches == 0


# Case 5: Live price ₹2,999 vs posted ₹2,400 -> expired, no alert. Out of stock -> expired.
def test_case_5_live_price_verification_expired() -> None:
    family_rates = {
        "whey_protein": FamilyRate(
            family_key="whey_protein", category="fitness", best_unit_rate_paise=289900, unit="g"
        ),
    }

    # 5a. Live price ₹2,999 vs posted ₹2,400 (> +5%) -> expired
    v_price_jumped = decide_verdict(
        post_text="MuscleBlaze Whey 1kg ₹2,400 : https://amzn.to/whey",
        posted_paise=240000,
        platform="amazon",
        sku="B0WHEY1000",
        tracked=None,
        keywords={"whey"},
        tracked_families={"whey_protein"},
        family_best_rates=family_rates,
        fetch_page=lambda: LivePage(
            listed_paise=299900,
            mrp_paise=349900,
            in_stock=True,
            title="MuscleBlaze Biozyme Whey Protein 1kg",
        ),
    )
    assert v_price_jumped.verdict == "expired"
    assert v_price_jumped.reasons == ["expired"]

    # 5b. Out of stock -> expired
    v_oos = decide_verdict(
        post_text="MuscleBlaze Whey 1kg ₹2,400 : https://amzn.to/whey",
        posted_paise=240000,
        platform="amazon",
        sku="B0WHEY1000",
        tracked=None,
        keywords={"whey"},
        tracked_families={"whey_protein"},
        family_best_rates=family_rates,
        fetch_page=lambda: LivePage(
            listed_paise=240000,
            mrp_paise=349900,
            in_stock=False,
            title="MuscleBlaze Biozyme Whey Protein 1kg",
        ),
    )
    assert v_oos.verdict == "expired"
    assert v_oos.reasons == ["expired"]


# Case 6: Dedupe, quiet hours (held then sent at 07:00), daily cap 10,
# Telegram skipped without token; token never in responses or caplog.
def test_case_6_alerts_dedupe_quiet_hours_daily_cap_and_secret_safety(
    session: Session,
    caplog: pytest.LogCaptureFixture,
) -> None:
    sent_requests: list[tuple[str, dict[str, Any]]] = []
    secret_bot_token = "999888777:AAH_super_secret_bot_token_xyz"

    def fake_post(url: str, payload: dict[str, Any]) -> tuple[int, str]:
        sent_requests.append((url, payload))
        return (200, '{"ok": true}')

    notifier = TelegramNotifier(
        bot_token=secret_bot_token,
        chat_id="12345678",
        http_post=fake_post,
    )

    day_time = datetime(2026, 10, 19, 14, 0, 0, tzinfo=UTC)

    # 6a. First alert during daytime -> sent immediately, no affiliate tag in message
    a1 = record_and_dispatch_alert(
        session=session,
        household_id=1,
        now_dt=day_time,
        product_key="amazon:B0WHEY1000",
        platform="amazon",
        sku="B0WHEY1000",
        title="Optimum Nutrition Whey 1kg",
        url="https://www.amazon.in/dp/B0WHEY1000",
        price_paise=240000,
        reasons=["beats_family_best"],
        notifier=notifier,
    )
    assert a1 is not None
    assert a1.telegram_status == "sent"
    assert len(sent_requests) == 1
    assert "Optimum Nutrition Whey 1kg" in sent_requests[0][1]["text"]
    assert "2,400" in sent_requests[0][1]["text"] or "2400" in sent_requests[0][1]["text"]
    assert "https://www.amazon.in/dp/B0WHEY1000" in sent_requests[0][1]["text"]
    assert "tag=" not in sent_requests[0][1]["text"]

    # 6b. Dedupe: same (product, price) within 24h -> skipped
    a1_dup = record_and_dispatch_alert(
        session=session,
        household_id=1,
        now_dt=day_time + timedelta(hours=2),
        product_key="amazon:B0WHEY1000",
        platform="amazon",
        sku="B0WHEY1000",
        title="Optimum Nutrition Whey 1kg",
        url="https://www.amazon.in/dp/B0WHEY1000",
        price_paise=240000,
        reasons=["beats_family_best"],
        notifier=notifier,
    )
    assert a1_dup is None
    assert len(sent_requests) == 1

    # 6c. Quiet hours (23:30) -> held until 07:00, then sent by send_due_alerts at 07:00
    quiet_time = datetime(2026, 10, 19, 23, 30, 0, tzinfo=UTC)
    a_quiet = record_and_dispatch_alert(
        session=session,
        household_id=1,
        now_dt=quiet_time,
        product_key="amazon:B0ALMOND01",
        platform="amazon",
        sku="B0ALMOND01",
        title="Happilo Almonds 1kg",
        url="https://www.amazon.in/dp/B0ALMOND01",
        price_paise=69900,
        reasons=["below_target"],
        notifier=notifier,
    )
    assert a_quiet is not None
    assert a_quiet.telegram_status == "held"
    assert a_quiet.scheduled_for == datetime(2026, 10, 20, 7, 0, 0, tzinfo=UTC)
    assert len(sent_requests) == 1  # Not sent yet!

    # Before 07:00 -> still held
    flushed_early = send_due_alerts(
        session,
        datetime(2026, 10, 20, 6, 59, 0, tzinfo=UTC),
        notifier,
    )
    assert flushed_early == 0
    assert len(sent_requests) == 1

    # At 07:00 -> sent!
    flushed_7am = send_due_alerts(
        session,
        datetime(2026, 10, 20, 7, 0, 0, tzinfo=UTC),
        notifier,
    )
    assert flushed_7am == 1
    assert len(sent_requests) == 2

    # 6d. Daily cap 10: we already created 2 alerts within 24h; create 8 more (total 10), 11th is capped
    morning = datetime(2026, 10, 20, 8, 0, 0, tzinfo=UTC)
    for i in range(8):
        created = record_and_dispatch_alert(
            session=session,
            household_id=1,
            now_dt=morning + timedelta(minutes=i),
            product_key=f"amazon:B0CAPITEM{i}",
            platform="amazon",
            sku=f"B0CAPITEM{i}",
            title=f"Cap Item {i}",
            url=f"https://www.amazon.in/dp/B0CAPITEM{i}",
            price_paise=10000 + i * 100,
            reasons=["below_target"],
            notifier=notifier,
        )
        assert created is not None

    # 11th alert in the 24h window -> None (daily cap 10)
    capped = record_and_dispatch_alert(
        session=session,
        household_id=1,
        now_dt=morning + timedelta(minutes=30),
        product_key="amazon:B0ELEVENTH",
        platform="amazon",
        sku="B0ELEVENTH",
        title="11th Item",
        url="https://www.amazon.in/dp/B0ELEVENTH",
        price_paise=19900,
        reasons=["below_target"],
        notifier=notifier,
    )
    assert capped is None
    assert len(session.exec(select(RadarAlert)).all()) == 10

    # 6e. Empty token or chat_id -> skipped silently without error
    empty_notifier = TelegramNotifier(bot_token="", chat_id="", http_post=fake_post)
    assert empty_notifier.send_alert(
        AlertPayload(
            title="Test",
            price_paise=10000,
            reasons=["below_target"],
            url="https://www.amazon.in/dp/B072HG4WNC",
        )
    ) is False

    # 6f. Token never in caplog
    assert secret_bot_token not in caplog.text
