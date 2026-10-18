from collections.abc import Generator
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from app.api.v1.sources import router as sources_router
from app.core.config import Settings
from app.core.db import current_user, get_session
from app.domain.models import AppUser, CustomListing, HouseholdMember, SourceStatus
from app.sources.fetcher import setup_fetcher_loop


@pytest.fixture
def test_app(engine: Engine) -> FastAPI:
    app = FastAPI()
    app.include_router(sources_router, prefix="/api/v1")

    def override_get_session() -> Generator[Session, None, None]:
        with Session(engine) as s:
            yield s

    app.dependency_overrides[get_session] = override_get_session
    return app


@pytest.fixture
def setup_users_and_household(engine: Engine) -> dict[str, Any]:
    with Session(engine) as s:
        owner = s.exec(select(AppUser).where(AppUser.email == "owner@dealscour.local")).first()
        assert owner.id is not None
        owner_id = owner.id

        member = s.exec(select(AppUser).where(AppUser.email == "member@dealscour.local")).first()
        if not member:
            member = AppUser(email="member@dealscour.local", name="Member")
            s.add(member)
            s.commit()
            s.refresh(member)

        assert member.id is not None
        member_id = member.id
        member_mem = s.get(HouseholdMember, (1, member_id))
        if not member_mem:
            member_mem = HouseholdMember(household_id=1, user_id=member_id, role="member")
            s.add(member_mem)
            s.commit()

        return {"owner_id": owner_id, "member_id": member_id, "household_id": 1}


def test_10_api_sources_status_shape(
    test_app: FastAPI,
    setup_users_and_household: dict[str, Any],
    engine: Engine,
) -> None:
    owner_id = setup_users_and_household["owner_id"]
    test_app.dependency_overrides[current_user] = lambda: AppUser(id=owner_id, email="owner@dealscour.local")

    with Session(engine) as s:
        s.add(
            SourceStatus(
                platform="amazon",
                consecutive_failures=1,
                last_error="HTTP 503",
                last_success_at=datetime(2026, 10, 19, 10, 0, 0, tzinfo=UTC),
            )
        )
        s.commit()

    with TestClient(test_app) as client:
        resp = client.get("/api/v1/sources/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["quick_commerce"] == "manual only (blocked by the sites)"
        assert "platforms" in data
        platforms = {p["platform"]: p for p in data["platforms"]}
        assert "amazon" in platforms
        assert "flipkart" in platforms

        amz = platforms["amazon"]
        assert amz["consecutive_failures"] == 1
        assert amz["last_error"] == "HTTP 503"
        assert amz["last_success_at"] is not None

        fk = platforms["flipkart"]
        assert fk["consecutive_failures"] == 0
        assert fk["disabled_until"] is None


def test_10_api_sources_refresh_permissions_and_concurrency(
    test_app: FastAPI,
    setup_users_and_household: dict[str, Any],
    engine: Engine,
) -> None:
    owner_id = setup_users_and_household["owner_id"]
    member_id = setup_users_and_household["member_id"]

    with Session(engine) as s:
        s.add(
            CustomListing(
                household_id=1,
                listing_id="amz-test-due-1",
                platform="amazon",
                sku="B0TEST1",
                url="https://amazon.in/dp/B0TEST1",
                title="Due Product 1",
                brand="Brand",
                pack_label="1kg",
                category="staples",
                product_key="pk_due_1",
                family_key="fk_due_1",
                created_at=datetime.now(UTC),
            )
        )
        s.commit()

    # 1. As member -> 403 Forbidden
    test_app.dependency_overrides[current_user] = lambda: AppUser(
        id=member_id, email="member@dealscour.local"
    )
    with TestClient(test_app) as client:
        resp = client.post("/api/v1/sources/refresh", headers={"X-DealScour": "1"})
        assert resp.status_code == 403

    # 2. As owner -> 202 Accepted with queued count
    test_app.dependency_overrides[current_user] = lambda: AppUser(id=owner_id, email="owner@dealscour.local")
    with TestClient(test_app) as client:
        resp = client.post("/api/v1/sources/refresh", headers={"X-DealScour": "1"})
        assert resp.status_code == 202
        assert resp.json() == {"queued": 1}

    # 3. Concurrent call while a refresh is in progress -> 409 Conflict
    from app.api.v1 import sources

    sources._in_progress_households.add(1)
    try:
        with TestClient(test_app) as client:
            resp = client.post("/api/v1/sources/refresh", headers={"X-DealScour": "1"})
            assert resp.status_code == 409
            assert "already in progress" in resp.json()["detail"]
    finally:
        sources._in_progress_households.discard(1)


def test_11_fetchers_enabled_scheduling(test_app: FastAPI, tmp_path: Any, monkeypatch: Any) -> None:
    import threading

    from app.sources import fetcher as fetcher_module

    disabled_settings = Settings(db_path=tmp_path / "test.db", secret_key="a" * 32, fetchers_enabled=False)
    assert setup_fetcher_loop(test_app, disabled_settings) is None
    assert getattr(test_app.state, "fetcher_loop_registered", False) is False

    # Enabled: exactly one worker thread is started (worker stubbed so nothing is fetched in tests)
    calls: list[int] = []
    monkeypatch.setattr(fetcher_module, "run_fetcher_worker", lambda engine, hours, stop: calls.append(hours))
    monkeypatch.setattr(fetcher_module, "_LOOP_STARTED", threading.Event())
    enabled_settings = Settings(db_path=tmp_path / "test.db", secret_key="a" * 32, fetchers_enabled=True)
    stop = setup_fetcher_loop(test_app, enabled_settings, engine=object())  # type: ignore[arg-type]
    assert stop is not None
    assert getattr(test_app.state, "fetcher_loop_registered", False) is True
    assert setup_fetcher_loop(test_app, enabled_settings, engine=object()) is None  # never a second loop
    for _ in range(50):
        if calls:
            break
        threading.Event().wait(0.01)
    assert calls == [enabled_settings.fetch_interval_hours]


def test_fetch_url_refuses_foreign_hosts_and_redirects() -> None:
    import pytest

    from app.sources.fetcher import FetchRefusedError, _check_url

    _check_url("https://www.amazon.in/dp/B072HG4WNC")
    _check_url("https://www.flipkart.com/x/p/itmabcdef?pid=ABCDEFGH")
    for bad in (
        "http://www.amazon.in/dp/B072HG4WNC",
        "https://127.0.0.1:8000/",
        "https://amazon.in.evil.com/",
        "https://blinkit.com/prn/x/prid/1",
    ):
        with pytest.raises(FetchRefusedError):
            _check_url(bad)
