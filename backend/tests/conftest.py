import os
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

# Set test environment variables before importing app
os.environ.setdefault("DEALSCOUR_SECRET_KEY", "test-secret-key-for-testing-only-32chars")
os.environ.setdefault("DEALSCOUR_OWNER_EMAIL", "owner@dealscour.local")
os.environ.setdefault("DEALSCOUR_DEV_LOGIN", "0")

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from app.api.v1.baskets import router as baskets_router
from app.api.v1.deals import router as deals_router
from app.api.v1.lists import router as lists_router
from app.api.v1.offers import router as offers_router
from app.api.v1.plans import router as plans_router
from app.api.v1.prices import router as prices_router
from app.core.db import create_db_engine, get_session
from app.core.security import hash_token
from app.domain.models import AppUser, AuthSession, HouseholdMember

TEST_SESSION_TOKEN = "test-persistent-session-token-for-tests-32ch"
_current_test_is_auth = False


def pytest_runtest_setup(item: pytest.Item) -> None:
    global _current_test_is_auth
    _current_test_is_auth = (
        "test_auth" in item.nodeid or "test_households" in item.nodeid
    )


# Wrap TestClient.request so that non-auth test suites transparently carry session & CSRF
_orig_testclient_request = TestClient.request


def _patched_testclient_request(self: TestClient, method: str, url: Any, *args: Any, **kwargs: Any) -> Any:
    if not _current_test_is_auth:
        if "ds_session" not in self.cookies and "ds_session" not in (kwargs.get("cookies") or {}):
            self.cookies.set("ds_session", TEST_SESSION_TOKEN)

        if (
            method.upper() in ("POST", "PATCH", "DELETE", "PUT")
            and "X-DealScour" not in self.headers
            and "X-DealScour" not in (kwargs.get("headers") or {})
        ):
            self.headers["X-DealScour"] = "1"

    return _orig_testclient_request(self, method, url, *args, **kwargs)


TestClient.request = _patched_testclient_request  # type: ignore[method-assign]


@pytest.fixture
def test_db_path(tmp_path: Path) -> Path:
    return tmp_path / "test.db"


def _seed_auth_user_and_session(engine: Engine) -> str:
    """Helper to seed owner user and return session token for household 1."""
    with Session(engine) as s:
        user = s.exec(select(AppUser).where(AppUser.email == "owner@dealscour.local")).first()
        if not user:
            user = AppUser(
                email="owner@dealscour.local",
                name="Test Owner",
                created_at=datetime.now(UTC),
            )
            s.add(user)
            s.commit()
            s.refresh(user)

        assert user.id is not None
        mem = s.exec(
            select(HouseholdMember).where(
                HouseholdMember.household_id == 1,
                HouseholdMember.user_id == user.id,
            )
        ).first()
        if not mem:
            mem = HouseholdMember(household_id=1, user_id=user.id, role="owner")
            s.add(mem)
            s.commit()

        token = TEST_SESSION_TOKEN
        token_h = hash_token(token)
        auth_sess = s.exec(select(AuthSession).where(AuthSession.token_hash == token_h)).first()
        if not auth_sess:
            auth_sess = AuthSession(
                token_hash=token_h,
                user_id=user.id,
                created_at=datetime.now(UTC),
                expires_at=datetime.now(UTC) + timedelta(days=365),
                last_seen_at=datetime.now(UTC),
            )
            s.add(auth_sess)
            s.commit()
        return token


@pytest.fixture
def engine(test_db_path: Path) -> Generator[Engine, None, None]:
    db_url = f"sqlite:///{test_db_path.resolve()}"
    alembic_cfg = Config(str(Path(__file__).parent.parent / "alembic.ini"))
    alembic_cfg.set_main_option("sqlalchemy.url", db_url)
    alembic_cfg.set_main_option("script_location", str(Path(__file__).parent.parent / "migrations"))
    command.upgrade(alembic_cfg, "head")

    eng = create_db_engine(test_db_path)
    if not _current_test_is_auth:
        _seed_auth_user_and_session(eng)
    try:
        yield eng
    finally:
        eng.dispose()


@pytest.fixture
def session(engine: Engine) -> Generator[Session, None, None]:
    with Session(engine) as s:
        yield s


@pytest.fixture
def authenticated_client(engine: Engine) -> Generator[TestClient, None, None]:
    app = FastAPI()
    app.include_router(lists_router, prefix="/api/v1")
    app.include_router(offers_router, prefix="/api/v1")
    app.include_router(baskets_router, prefix="/api/v1")
    app.include_router(plans_router, prefix="/api/v1")
    app.include_router(deals_router, prefix="/api/v1")
    app.include_router(prices_router, prefix="/api/v1")

    def override_get_session() -> Generator[Session, None, None]:
        with Session(engine) as s:
            yield s

    app.dependency_overrides[get_session] = override_get_session
    token = _seed_auth_user_and_session(engine)

    with TestClient(app) as c:
        c.cookies.set("ds_session", token)
        c.headers["X-DealScour"] = "1"
        yield c


@pytest.fixture
def client(authenticated_client: TestClient) -> Generator[TestClient, None, None]:
    """Default client fixture is authenticated so existing tests pass seamlessly."""
    yield authenticated_client
