from collections.abc import Generator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from app.api.v1.radar import get_notifier, get_page_fetcher, get_resolver
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
    RadarChannel,
    RadarKeyword,
    RadarPost,
)
from app.notify.base import AlertPayload
from app.radar.links import LinkResolver, ResolvedLink
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

    def fake_resolve(url: str) -> ResolvedLink:
        if "amzn.to/butter" in url or "B0BUTTER01" in url:
            return ResolvedLink(
                status="ok",
                ref=ProductRef(
                    platform="amazon",
                    sku="B0BUTTER01",
                    url="https://www.amazon.in/dp/B0BUTTER01",
                ),
            )
        if "amzn.to/whey" in url or "B0WHEY1000" in url:
            return ResolvedLink(
                status="ok",
                ref=ProductRef(
                    platform="amazon",
                    sku="B0WHEY1000",
                    url="https://www.amazon.in/dp/B0WHEY1000",
                ),
            )
        if "amzn.to/expired" in url or "B0EXPIRED1" in url:
            return ResolvedLink(
                status="ok",
                ref=ProductRef(
                    platform="amazon",
                    sku="B0EXPIRED1",
                    url="https://www.amazon.in/dp/B0EXPIRED1",
                ),
            )
        return ResolvedLink(status="unsupported", ref=None, reason="unsupported_link")

    def fake_page_fetch(platform: str, url: str) -> LivePage:
        if "B0BUTTER01" in url:
            return LivePage(
                listed_paise=29000,
                mrp_paise=32000,
                in_stock=True,
                title="Amul Butter 500g",
            )
        if "B0WHEY1000" in url:
            return LivePage(
                listed_paise=240000,
                mrp_paise=329900,
                in_stock=True,
                title="Optimum Nutrition Whey Protein 1kg",
            )
        if "B0EXPIRED1" in url:
            return LivePage(
                listed_paise=299900,
                mrp_paise=329900,
                in_stock=True,
                title="Optimum Nutrition Whey Protein 1kg",
            )
        raise AssertionError(f"Unexpected page fetch for {url}")

    resolver = LinkResolver(
        http_fetch=lambda u, m: (404, {}, b""),
        now=lambda: FIXED_NOW,
        sleep=lambda s: None,
    )
    resolver.resolve = fake_resolve  # type: ignore[method-assign]

    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[clock.now] = lambda: FIXED_NOW
    app.dependency_overrides[get_notifier] = lambda: fake_notifier
    app.dependency_overrides[get_resolver] = lambda: resolver
    app.dependency_overrides[get_page_fetcher] = lambda: fake_page_fetch

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
    assert ingest_unlisted.json()["processed"] == 0
    assert ingest_unlisted.json()["ignored"] == 2
    assert len(fake_notifier.sent) == 0

    with Session(engine) as s:
        assert s.exec(select(RadarPost)).all() == []

    # Now post from household 1's enabled channel -> processed, GOOD verdict, alert sent, observation saved!
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
                },
                {
                    "peer_id": "-1001191090845",
                    "message_id": "102",
                    "text": "Whey 1kg @2400 https://amzn.to/expired",
                    "links": ["https://amzn.to/expired"],
                },
            ]
        },
    )
    assert ingest_good.status_code == 200
    body = ingest_good.json()
    assert body["processed"] == 2
    assert body["alerts_created"] == 1
    assert len(fake_notifier.sent) == 1
    assert fake_notifier.sent[0].price_paise == 29000

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
