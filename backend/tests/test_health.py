from fastapi.testclient import TestClient

from app.main import app


def test_health() -> None:
    res = TestClient(app).get("/api/v1/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


def test_deals_router_is_mounted() -> None:
    res = TestClient(app).get("/api/v1/deals", params={"q": "aashirvaad"})
    assert res.status_code == 200
    assert res.json()["count"] == 3
