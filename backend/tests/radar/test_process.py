"""Round 2: background processing of pending radar posts (items 19-23)."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlmodel import Session, select

from app.domain.models import (
    CustomListing,
    ListingWatch,
    PriceObservation,
    RadarAlert,
    RadarKeyword,
    RadarPost,
)
from app.notify.base import AlertPayload
from app.radar.links import ResolvedLink
from app.radar.posts import pairs_to_json, parse_post
from app.radar.process import process_pending_posts
from app.radar.verdict import LivePage
from app.sources.urls import ProductRef

FIXED_NOW = datetime(2026, 10, 19, 14, 0, 0, tzinfo=UTC)
PEER = "-1001191090845"


class FakeNotifier:
    def __init__(self) -> None:
        self.sent: list[AlertPayload] = []

    def send_alert(self, alert: AlertPayload) -> bool:
        self.sent.append(alert)
        return True


class FakeResolver:
    def __init__(self, routes: dict[str, ResolvedLink] | None = None) -> None:
        self.routes = routes or {}
        self.calls: list[str] = []

    def resolve(self, raw_url: str) -> ResolvedLink:
        self.calls.append(raw_url)
        return self.routes.get(
            raw_url, ResolvedLink(status="unsupported", ref=None, reason="unsupported_link")
        )


class FakePageFetcher:
    def __init__(self, pages: dict[str, LivePage] | None = None) -> None:
        self.pages = pages or {}
        self.calls: list[tuple[str, str]] = []

    def __call__(self, platform: str, url: str) -> LivePage | None:
        self.calls.append((platform, url))
        return self.pages.get(url)


def _amazon_link(slug: str, sku: str) -> ResolvedLink:
    return ResolvedLink(
        status="ok",
        ref=ProductRef(platform="amazon", sku=sku, url=f"https://www.amazon.in/dp/{sku}"),
        final_url=f"https://www.amazon.in/{slug}/dp/{sku}?tag=offerbox-21",
    )


def _pending_post(
    session: Session,
    *,
    message_id: str,
    text: str,
    posted_at: datetime | None = None,
) -> RadarPost:
    row = RadarPost(
        household_id=1,
        peer_id=PEER,
        message_id=message_id,
        text=text,
        posted_at=posted_at or FIXED_NOW - timedelta(minutes=5),
        verdict="pending",
        reasons_json='["pending"]',
        status="pending",
        pairs_json=pairs_to_json(parse_post(text)),
        created_at=FIXED_NOW - timedelta(minutes=5),
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def _seed_tracked_butter(session: Session) -> None:
    session.add(
        CustomListing(
            household_id=1,
            listing_id="cus-butter",
            platform="amazon",
            sku="B0BUTTER01",
            url="https://www.amazon.in/dp/B0BUTTER01",
            title="Amul Butter 500g",
            brand="Amul",
            pack_label="500g",
            category="dairy",
            product_key="amul_butter_500g",
            family_key="butter",
            created_at=FIXED_NOW,
        )
    )
    session.add(
        ListingWatch(household_id=1, listing_id="cus-butter", target_paise=30000, created_at=FIXED_NOW)
    )
    session.add(
        PriceObservation(
            household_id=1,
            listing_id="cus-butter",
            listed_paise=31000,
            mrp_paise=32000,
            in_stock=True,
            source="manual",
            observed_at=FIXED_NOW - timedelta(hours=2),
        )
    )
    session.commit()


def _reload(session: Session, row: RadarPost) -> RadarPost:
    session.expire_all()
    fresh = session.get(RadarPost, row.id)
    assert fresh is not None
    return fresh


# Item 19: oldest first, up to `limit`, each marked done with its verdict.
def test_process_pending_posts_handles_up_to_limit_oldest_first(session: Session) -> None:
    rows = []
    for message_id, age_minutes in (("5", 10), ("2", 50), ("4", 20), ("1", 60), ("3", 30)):
        rows.append(
            _pending_post(
                session,
                message_id=message_id,
                text=f"Deal ₹99 : https://amzn.to/{message_id}",
                posted_at=FIXED_NOW - timedelta(minutes=age_minutes),
            )
        )
    resolver = FakeResolver()
    fetcher = FakePageFetcher()

    handled = process_pending_posts(
        session, FIXED_NOW, resolver=resolver, page_fetcher=fetcher, notifier=FakeNotifier(), limit=3
    )

    assert handled == 3
    assert resolver.calls == [
        "https://amzn.to/1",
        "https://amzn.to/2",
        "https://amzn.to/3",
    ]
    by_msg = {r.message_id: _reload(session, r) for r in rows}
    for done_id in ("1", "2", "3"):
        assert by_msg[done_id].status == "done"
        assert by_msg[done_id].verdict == "unsupported_link"
    for pending_id in ("4", "5"):
        assert by_msg[pending_id].status == "pending"
        assert by_msg[pending_id].verdict == "pending"

    # The remainder is picked up by the next run.
    assert (
        process_pending_posts(
            session, FIXED_NOW, resolver=resolver, page_fetcher=fetcher, notifier=FakeNotifier()
        )
        == 2
    )
    assert fetcher.calls == []


# Item 20 / 23: relevance gate uses post text AND the resolved URL slug before any page fetch.
def test_irrelevant_slug_is_not_fetched_even_when_post_text_has_no_product_words(
    session: Session,
) -> None:
    session.add(RadarKeyword(household_id=1, keyword="almonds", created_at=FIXED_NOW))
    session.commit()
    luggage = _pending_post(session, message_id="10", text="Loot ₹99 : https://amzn.to/lug")
    almonds = _pending_post(session, message_id="11", text="Loot ₹399 : https://amzn.to/alm")
    resolver = FakeResolver(
        {
            "https://amzn.to/lug": _amazon_link("American-Tourister-Luggage", "B0LUGGAGE1"),
            "https://amzn.to/alm": _amazon_link("Happilo-Almonds-500g", "B0ALMONDS1"),
        }
    )
    fetcher = FakePageFetcher(
        {
            "https://www.amazon.in/dp/B0ALMONDS1": LivePage(
                listed_paise=39900, in_stock=True, title="Happilo Premium Almonds 500g"
            )
        }
    )

    assert (
        process_pending_posts(
            session, FIXED_NOW, resolver=resolver, page_fetcher=fetcher, notifier=FakeNotifier()
        )
        == 2
    )

    lug = _reload(session, luggage)
    assert lug.verdict == "not_relevant"
    assert lug.status == "done"
    assert lug.page_fetches == 0
    # Only the almonds page was fetched; luggage never was.
    assert fetcher.calls == [("amazon", "https://www.amazon.in/dp/B0ALMONDS1")]
    assert _reload(session, almonds).page_fetches == 1


# Item 20: daily budget for untracked fetches, counted from stored verdicts.
def test_untracked_fetch_budget_is_counted_from_stored_posts(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEALSCOUR_RADAR_MAX_PAGE_FETCHES_PER_DAY", "2")
    session.add(RadarKeyword(household_id=1, keyword="almonds", created_at=FIXED_NOW))
    # 2 fetches yesterday (outside the 24 h window) do not count; 1 fetch an hour ago does.
    for message_id, fetches, hours_ago in (("old", 2, 25), ("recent", 1, 1)):
        session.add(
            RadarPost(
                household_id=1,
                peer_id=PEER,
                message_id=message_id,
                text="x",
                posted_at=FIXED_NOW - timedelta(hours=hours_ago),
                verdict="not_relevant",
                reasons_json='["not_relevant"]',
                status="done",
                page_fetches=fetches,
                processed_at=FIXED_NOW - timedelta(hours=hours_ago),
                created_at=FIXED_NOW - timedelta(hours=hours_ago),
            )
        )
    session.commit()
    first = _pending_post(session, message_id="20", text="Almonds ₹399 : https://amzn.to/a1")
    second = _pending_post(session, message_id="21", text="Almonds ₹399 : https://amzn.to/a2")
    resolver = FakeResolver(
        {
            "https://amzn.to/a1": _amazon_link("Happilo-Almonds-500g", "B0ALMONDS1"),
            "https://amzn.to/a2": _amazon_link("Tata-Almonds-500g", "B0ALMONDS2"),
        }
    )
    fetcher = FakePageFetcher()

    process_pending_posts(
        session, FIXED_NOW, resolver=resolver, page_fetcher=fetcher, notifier=FakeNotifier()
    )

    # One slot left: the first post fetches, the second is skipped without a fetch.
    assert len(fetcher.calls) == 1
    assert _reload(session, first).page_fetches == 1
    skipped = _reload(session, second)
    assert skipped.verdict == "skipped_budget"
    assert skipped.status == "done"
    assert skipped.page_fetches == 0


def test_spent_budget_skips_untracked_but_tracked_products_still_verify_live(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEALSCOUR_RADAR_MAX_PAGE_FETCHES_PER_DAY", "0")
    _seed_tracked_butter(session)
    session.add(RadarKeyword(household_id=1, keyword="almonds", created_at=FIXED_NOW))
    session.commit()
    almonds = _pending_post(session, message_id="30", text="Almonds ₹399 : https://amzn.to/alm")
    butter = _pending_post(session, message_id="31", text="Butter ₹290 : https://amzn.to/butter")
    resolver = FakeResolver(
        {
            "https://amzn.to/alm": _amazon_link("Happilo-Almonds-500g", "B0ALMONDS1"),
            "https://amzn.to/butter": _amazon_link("Amul-Butter-500g", "B0BUTTER01"),
        }
    )
    fetcher = FakePageFetcher(
        {
            "https://www.amazon.in/dp/B0BUTTER01": LivePage(
                listed_paise=29000, mrp_paise=32000, in_stock=True, title="Amul Butter 500g"
            )
        }
    )
    notifier = FakeNotifier()

    process_pending_posts(session, FIXED_NOW, resolver=resolver, page_fetcher=fetcher, notifier=notifier)

    assert _reload(session, almonds).verdict == "skipped_budget"
    assert fetcher.calls == [("amazon", "https://www.amazon.in/dp/B0BUTTER01")]
    good = _reload(session, butter)
    assert good.verdict == "good"
    assert good.page_fetches == 0  # tracked fetches are not charged to the untracked budget
    assert [a.price_paise for a in notifier.sent] == [29000]
    alerts = session.exec(select(RadarAlert)).all()
    assert len(alerts) == 1
    assert alerts[0].url == "https://www.amazon.in/dp/B0BUTTER01"


# Item 21: backlog is never processed.
def test_post_older_than_max_age_is_too_old_and_never_resolved(session: Session) -> None:
    stale = _pending_post(
        session,
        message_id="40",
        text="Loot ₹99 : https://amzn.to/x",
        posted_at=FIXED_NOW - timedelta(hours=7),
    )
    fresh = _pending_post(
        session,
        message_id="41",
        text="Loot ₹99 : https://amzn.to/y",
        posted_at=FIXED_NOW - timedelta(hours=5),
    )
    resolver = FakeResolver()

    process_pending_posts(
        session, FIXED_NOW, resolver=resolver, page_fetcher=FakePageFetcher(), notifier=FakeNotifier()
    )

    assert resolver.calls == ["https://amzn.to/y"]
    old = _reload(session, stale)
    assert old.status == "too_old"
    assert old.verdict == "too_old"
    assert _reload(session, fresh).status == "done"


def test_max_post_age_is_configurable(session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEALSCOUR_RADAR_MAX_POST_AGE_HOURS", "1")
    row = _pending_post(
        session,
        message_id="50",
        text="Loot ₹99 : https://amzn.to/x",
        posted_at=FIXED_NOW - timedelta(hours=2),
    )
    resolver = FakeResolver()

    process_pending_posts(
        session, FIXED_NOW, resolver=resolver, page_fetcher=FakePageFetcher(), notifier=FakeNotifier()
    )

    assert resolver.calls == []
    assert _reload(session, row).status == "too_old"


def test_a_failing_post_does_not_block_the_queue(session: Session) -> None:
    class ExplodingResolver(FakeResolver):
        def resolve(self, raw_url: str) -> ResolvedLink:
            if raw_url.endswith("/boom"):
                raise RuntimeError("network down")
            return super().resolve(raw_url)

    first = _pending_post(
        session,
        message_id="60",
        text="Deal ₹99 : https://amzn.to/boom",
        posted_at=FIXED_NOW - timedelta(minutes=30),
    )
    second = _pending_post(session, message_id="61", text="Deal ₹99 : https://amzn.to/ok")

    handled = process_pending_posts(
        session,
        FIXED_NOW,
        resolver=ExplodingResolver(),
        page_fetcher=FakePageFetcher(),
        notifier=FakeNotifier(),
    )

    assert handled == 2
    assert _reload(session, first).status == "done"
    assert _reload(session, second).status == "done"
