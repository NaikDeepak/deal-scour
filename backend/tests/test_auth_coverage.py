"""Every /api/v1 route is closed by default: no session → 401/403; mutating without CSRF header → 403.

Walks the real app's route table so a router added later without auth fails this test.
"""

import re
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlmodel import Session

from app.core.db import get_session
from app.main import app
from tests.conftest import _seed_auth_user_and_session

PUBLIC = {("GET", "/api/v1/health")}
MUTATING = {"POST", "PATCH", "PUT", "DELETE"}


def _routes() -> list[tuple[str, str]]:
    # The OpenAPI schema lists every endpoint (routers are mounted lazily in this FastAPI version).
    out = []
    for path, ops in app.openapi()["paths"].items():
        if not path.startswith("/api/v1"):
            continue
        for method in ops:
            m = method.upper()
            if m in {"GET", "POST", "PATCH", "PUT", "DELETE"} and (m, path) not in PUBLIC:
                out.append((m, re.sub(r"\{[^}]+\}", "1", path)))
    return out


@pytest.fixture
def real_app_client(engine: Engine) -> Generator[TestClient, None, None]:
    def override() -> Generator[Session, None, None]:
        with Session(engine) as s:
            yield s

    app.dependency_overrides[get_session] = override
    try:
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c
    finally:
        app.dependency_overrides.pop(get_session, None)


def test_route_table_is_not_empty() -> None:
    paths = {p for _, p in _routes()}
    for expected in ("/api/v1/lists", "/api/v1/offers", "/api/v1/baskets", "/api/v1/plans", "/api/v1/prices",
                     "/api/v1/deals", "/api/v1/auth/me", "/api/v1/households/members"):
        assert expected in paths


def test_every_route_rejects_anonymous(real_app_client: TestClient) -> None:
    for method, path in _routes():
        res = real_app_client.request(method, path, json={})
        assert res.status_code in (401, 403), f"{method} {path} → {res.status_code} without a session"


def test_every_mutating_route_requires_csrf_header(real_app_client: TestClient, engine: Engine) -> None:
    real_app_client.cookies.set("ds_session", _seed_auth_user_and_session(engine))
    for method, path in _routes():
        if method in MUTATING:
            res = real_app_client.request(method, path, json={})
            assert res.status_code == 403, f"{method} {path} → {res.status_code} without X-DealScour"
