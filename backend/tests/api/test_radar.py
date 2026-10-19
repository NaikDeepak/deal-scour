import json
import time
from collections.abc import Generator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlmodel import Session, col, select

from app.api.v1.radar import get_notifier
from app.api.v1.radar import router as radar_router
from app.core import clock
from app.core.db import get_session
from app.core.security import hash_token
from app.domain.models import (
    AppUser,
    AuthSession,
    CustomListing,
    Household,
    HouseholdMember,
    ListingWatch,
    PriceObservation,
    RadarAlert,
    RadarChannel,
    RadarKeyword,
    RadarPost,
)
from app.notify.base import AlertPayload
from app.radar import process as radar_process
from app.radar.links import LinkResolver, ResolvedLink
from app.radar.process import process_pending_posts
from app.radar.verdict import LivePage
from app.sources.urls import ProductRef

FIXED_NOW = datetime(2026, 10, 19, 14, 0, 0, tzinfo=UTC)
SESSION_TOKEN = "test-persistent-session-token-for-tests-32ch"


class FakeNotifier:
    def __init__(self) -> None:
        self.sent: list[AlertPayload] = []

    def send_alert(self, alert: AlertPayload) -> bool:
        self.sent.append(alert)
        return True


def _amazon(slug: str, sku: str) -> ResolvedLink:
    return ResolvedLink(
        status="ok",
        ref=ProductRef(platform="amazon", sku=sku, url=f"https://www.amazon.in/dp/{sku}"),
        final_url=f"https://www.amazon.in/{slug}/dp/{sku}?tag=offerbox-21",
    )


class FakeResolver:
    def resolve(self, raw_url: str) -> ResolvedLink:
        if "amzn.to/butter" in raw_url:
            return _amazon("Amul-Butter-500g", "B0BUTTER01")
        if "amzn.to/expired" in raw_url:
            return _amazon("Optimum-Nutrition-Whey-Protein-1kg", "B0EXPIRED1")
        return ResolvedLink(status="unsupported", ref=None, reason="unsupported_link")


def fake_page_fetch(platform: str, url: str) -> LivePage:
    if "B0BUTTER01" in url:
        return LivePage(listed_paise=29000, mrp_paise=32000, in_stock=True, title="Amul Butter 500g")
    if "B0EXPIRED1" in url:
        return LivePage(
            listed_paise=299900,
            mrp_paise=329900,
            in_stock=True,
            title="Optimum Nutrition Whey Protein 1kg",
        )
    raise AssertionError(f"Unexpected page fetch for {url}")


class _NetworkSpy:
    def __init__(self) -> None:
        self.resolver_calls: list[str] = []
        self.page_calls: list[tuple[str, str]] = []


@pytest.fixture
def network(monkeypatch: pytest.MonkeyPatch) -> _NetworkSpy:
    """Any resolver or page-fetch call made through the real code paths is recorded."""
    spy = _NetworkSpy()

    def spy_resolve(self: LinkResolver, raw_url: str) -> ResolvedLink:
        spy.resolver_calls.append(raw_url)
        return ResolvedLink(status="unsupported", ref=None, reason="unsupported_link")

    def spy_page(platform: str, url: str) -> LivePage | None:
        spy.page_calls.append((platform, url))
        return None

    monkeypatch.setattr(LinkResolver, "resolve", spy_resolve)
    monkeypatch.setattr(radar_process, "default_page_fetcher", spy_page)
    return spy


@pytest.fixture
def fake_notifier() -> FakeNotifier:
    return FakeNotifier()


@pytest.fixture
def radar_client(
    engine: Engine,
    fake_notifier: FakeNotifier,
) -> Generator[TestClient, None, None]:
    app = FastAPI()
    app.include_router(radar_router, prefix="/api/v1")

    def override_get_session() -> Generator[Session, None, None]:
        with Session(engine) as s:
            yield s

    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[clock.now] = lambda: FIXED_NOW
    app.dependency_overrides[get_notifier] = lambda: fake_notifier

    with Session(engine) as s:
        user1 = s.exec(select(AppUser).where(AppUser.email == "owner@dealscour.local")).first()
        if not user1:
            user1 = AppUser(email="owner@dealscour.local", name="Owner", created_at=FIXED_NOW)
            s.add(user1)
            s.commit()
            s.refresh(user1)
        assert user1.id is not None
        mem1 = s.exec(
            select(HouseholdMember).where(
                HouseholdMember.household_id == 1,
                HouseholdMember.user_id == user1.id,
            )
        ).first()
        if not mem1:
            s.add(HouseholdMember(household_id=1, user_id=user1.id, role="owner"))
            s.commit()
        th = hash_token(SESSION_TOKEN)
        if not s.exec(select(AuthSession).where(AuthSession.token_hash == th)).first():
            s.add(
                AuthSession(
                    token_hash=th,
                    user_id=user1.id,
                    created_at=FIXED_NOW,
                    expires_at=FIXED_NOW + timedelta(days=365),
                    last_seen_at=FIXED_NOW,
                )
            )
            s.commit()

        # Seed household 2
        if not s.get(Household, 2):
            s.add(Household(id=2, name="Other Household", pincode="400001"))
            s.commit()

    with TestClient(app) as c:
        c.cookies.set("ds_session", SESSION_TOKEN)
        c.headers["X-DealScour"] = "1"
        yield c


# Case 10: Token: create -> bearer works on posts/alerts; second create -> the first is 401;
# the token never appears in GET responses or caplog; a session cookie alone on /radar/posts -> 401.
def test_case_10_extension_token_lifecycle_and_bearer_only_auth(
    radar_client: TestClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # 1. Session cookie alone on /radar/posts and /radar/alerts -> 401
    res_no_bearer_posts = radar_client.post("/api/v1/radar/posts", json={"posts": []})
    assert res_no_bearer_posts.status_code == 401

    res_no_bearer_alerts = radar_client.get("/api/v1/radar/alerts")
    assert res_no_bearer_alerts.status_code == 401

    # 2. Create first extension token (with session + CSRF)
    tok1_res = radar_client.post("/api/v1/radar/extension-token")
    assert tok1_res.status_code == 200
    tok1 = tok1_res.json()["token"]
    assert isinstance(tok1, str) and len(tok1) >= 32

    # 3. Bearer works on /radar/posts, /radar/alerts, and /radar/channels
    res_posts_ok = radar_client.post(
        "/api/v1/radar/posts",
        json={"posts": []},
        headers={"Authorization": f"Bearer {tok1}"},
    )
    assert res_posts_ok.status_code == 200

    res_alerts_ok = radar_client.get(
        "/api/v1/radar/alerts",
        headers={"Authorization": f"Bearer {tok1}"},
    )
    assert res_alerts_ok.status_code == 200

    res_channels_ok = radar_client.get(
        "/api/v1/radar/channels",
        headers={"Authorization": f"Bearer {tok1}"},
    )
    assert res_channels_ok.status_code == 200

    # 4. Second create revokes the first token -> first is 401, second works
    tok2_res = radar_client.post("/api/v1/radar/extension-token")
    assert tok2_res.status_code == 200
    tok2 = tok2_res.json()["token"]
    assert tok2 != tok1

    res_old_tok = radar_client.post(
        "/api/v1/radar/posts",
        json={"posts": []},
        headers={"Authorization": f"Bearer {tok1}"},
    )
    assert res_old_tok.status_code == 401

    res_old_alerts = radar_client.get(
        "/api/v1/radar/alerts",
        headers={"Authorization": f"Bearer {tok1}"},
    )
    assert res_old_alerts.status_code == 401

    res_new_tok = radar_client.post(
        "/api/v1/radar/posts",
        json={"posts": []},
        headers={"Authorization": f"Bearer {tok2}"},
    )
    assert res_new_tok.status_code == 200

    # 5. Token never appears in any GET response or caplog
    for get_path in ("/api/v1/radar/channels", "/api/v1/radar/keywords", "/api/v1/radar/posts"):
        r = radar_client.get(get_path)
        assert r.status_code == 200
        assert tok1 not in r.text
        assert tok2 not in r.text

    assert tok1 not in caplog.text
    assert tok2 not in caplog.text


# Case 7: Posts from a channel not on the list -> 422/ignored. Another household's channel -> ignored.
def test_case_7_channel_allowlist_and_household_isolation(
    radar_client: TestClient,
    engine: Engine,
    fake_notifier: FakeNotifier,
    network: _NetworkSpy,
) -> None:
    tok = radar_client.post("/api/v1/radar/extension-token").json()["token"]
    bearer = {"Authorization": f"Bearer {tok}"}

    # Add enabled channel for household 1 and enabled channel for household 2
    ch_res = radar_client.post(
        "/api/v1/radar/channels",
        json={"peer_id": "https://web.telegram.org/k/#-1001191090845", "name": "Offer Box 2.0"},
    )
    assert ch_res.status_code == 200
    assert ch_res.json()["peer_id"] == "-1001191090845"

    with Session(engine) as s:
        s.add(
            RadarChannel(
                household_id=2,
                peer_id="-1009999999999",
                name="Household 2 Channel",
                enabled=True,
                created_at=FIXED_NOW,
            )
        )
        # Seed tracked butter for household 1 with target ₹300
        cl = CustomListing(
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
        s.add(cl)
        s.add(ListingWatch(household_id=1, listing_id="cus-butter", target_paise=30000, created_at=FIXED_NOW))
        s.add(
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
        # Seed family best for whey_protein (₹2,899/kg) and keyword "whey"
        cl_whey = CustomListing(
            household_id=1,
            listing_id="cus-whey-ref",
            platform="amazon",
            sku="B0WHEYREF1",
            url="https://www.amazon.in/dp/B0WHEYREF1",
            title="Reference Whey 1kg",
            brand="MuscleBlaze",
            pack_label="1kg",
            category="fitness",
            product_key="mb_whey_1kg",
            family_key="whey_protein",
            created_at=FIXED_NOW,
        )
        s.add(cl_whey)
        s.add(
            PriceObservation(
                household_id=1,
                listing_id="cus-whey-ref",
                listed_paise=289900,
                mrp_paise=349900,
                in_stock=True,
                source="manual",
                observed_at=FIXED_NOW - timedelta(hours=1),
            )
        )
        s.add(RadarKeyword(household_id=1, keyword="whey", created_at=FIXED_NOW))
        s.commit()

    # Post from unlisted channel AND from household 2's channel -> both ignored!
    ingest_unlisted = radar_client.post(
        "/api/v1/radar/posts",
        headers=bearer,
        json={
            "posts": [
                {
                    "peer_id": "-1005555555555",
                    "message_id": "10",
                    "text": "Amul Butter ₹290 : https://amzn.to/butter",
                    "links": ["https://amzn.to/butter"],
                },
                {
                    "peer_id": "-1009999999999",
                    "message_id": "11",
                    "text": "Amul Butter ₹290 : https://amzn.to/butter",
                    "links": ["https://amzn.to/butter"],
                },
            ]
        },
    )
    assert ingest_unlisted.status_code == 200
    assert ingest_unlisted.json()["accepted"] == 0
    assert ingest_unlisted.json()["ignored"] == 2
    assert len(fake_notifier.sent) == 0

    with Session(engine) as s:
        assert s.exec(select(RadarPost)).all() == []

    # Now post from household 1's enabled channel. Ingest only stores pending posts: it makes no
    # resolver, page or notifier calls (item 19).
    started = time.perf_counter()
    ingest_good = radar_client.post(
        "/api/v1/radar/posts",
        headers=bearer,
        json={
            "posts": [
                {
                    "peer_id": "#-1001191090845",
                    "message_id": "101",
                    "text": "Loot ₹290 : https://amzn.to/butter",
                    "links": ["https://amzn.to/butter"],
                    "posted_at": (FIXED_NOW - timedelta(minutes=1)).isoformat(),
                },
                {
                    "peer_id": "-1001191090845",
                    "message_id": "102",
                    "text": "Whey 1kg @2400 https://amzn.to/expired",
                    "links": ["https://amzn.to/expired"],
                    "posted_at": (FIXED_NOW - timedelta(minutes=1)).isoformat(),
                },
            ]
        },
    )
    assert time.perf_counter() - started < 1.0
    assert ingest_good.status_code == 200
    body = ingest_good.json()
    assert body["accepted"] == 2
    assert [p["verdict"] for p in body["posts"]] == ["pending", "pending"]
    assert network.resolver_calls == []
    assert network.page_calls == []
    assert len(fake_notifier.sent) == 0

    with Session(engine) as s:
        rows = s.exec(select(RadarPost).order_by(col(RadarPost.id))).all()
        assert [r.status for r in rows] == ["pending", "pending"]
        assert json.loads(rows[0].pairs_json) == [
            {"price_paise": 29000, "url": "https://amzn.to/butter"}
        ]
        assert s.exec(select(RadarAlert)).all() == []

    # Re-posting the same message ids is deduped.
    dup = radar_client.post(
        "/api/v1/radar/posts",
        headers=bearer,
        json={
            "posts": [
                {"peer_id": "-1001191090845", "message_id": "101", "text": "x", "links": []},
            ]
        },
    )
    assert dup.json()["deduped"] == 1
    assert dup.json()["accepted"] == 0

    # The background step resolves, decides and alerts.
    with Session(engine) as s:
        handled = process_pending_posts(
            s,
            FIXED_NOW,
            resolver=FakeResolver(),
            page_fetcher=fake_page_fetch,
            notifier=fake_notifier,
        )
    assert handled == 2
    assert len(fake_notifier.sent) == 1
    assert fake_notifier.sent[0].price_paise == 29000

    posts_res = radar_client.get("/api/v1/radar/posts")
    verdicts = {p["message_id"]: p["verdict"] for p in posts_res.json()["posts"]}
    assert verdicts == {"101": "good", "102": "expired"}

    # Verify browser alerts polling endpoint GET /radar/alerts
    alerts_res = radar_client.get("/api/v1/radar/alerts", headers=bearer)
    assert alerts_res.status_code == 200
    alerts = alerts_res.json()["alerts"]
    assert len(alerts) == 1
    assert alerts[0]["url"] == "https://www.amazon.in/dp/B0BUTTER01"
    assert alerts[0]["price_paise"] == 29000

    # Verify live price was saved as a fetcher PriceObservation for tracked item
    with Session(engine) as s:
        fetcher_obs = s.exec(
            select(PriceObservation).where(
                PriceObservation.household_id == 1,
                PriceObservation.listing_id == "cus-butter",
                PriceObservation.source == "fetcher",
            )
        ).all()
        assert len(fetcher_obs) == 1
        assert fetcher_obs[0].listed_paise == 29000


# Item 21 / 23: a backlog post (7 h old) is stored as too_old and never resolved or fetched.
def test_ingest_stores_backlog_post_as_too_old_without_any_network_calls(
    radar_client: TestClient,
    engine: Engine,
    network: _NetworkSpy,
) -> None:
    tok = radar_client.post("/api/v1/radar/extension-token").json()["token"]
    radar_client.post(
        "/api/v1/radar/channels",
        json={"peer_id": "-1001191090845", "name": "Offer Box 2.0"},
    )

    res = radar_client.post(
        "/api/v1/radar/posts",
        headers={"Authorization": f"Bearer {tok}"},
        json={
            "posts": [
                {
                    "peer_id": "-1001191090845",
                    "message_id": "7h",
                    "text": "Loot ₹99 : https://amzn.to/x",
                    "links": ["https://amzn.to/x"],
                    "posted_at": (FIXED_NOW - timedelta(hours=7)).isoformat(),
                },
                {
                    "peer_id": "-1001191090845",
                    "message_id": "1h",
                    "text": "Loot ₹99 : https://amzn.to/y",
                    "links": ["https://amzn.to/y"],
                    "posted_at": (FIXED_NOW - timedelta(hours=1)).isoformat(),
                },
            ]
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["accepted"] == 1
    assert body["too_old"] == 1
    assert network.resolver_calls == []
    assert network.page_calls == []

    with Session(engine) as s:
        by_msg = {r.message_id: r for r in s.exec(select(RadarPost)).all()}
        assert by_msg["7h"].status == "too_old"
        assert by_msg["7h"].verdict == "too_old"
        assert by_msg["1h"].status == "pending"
