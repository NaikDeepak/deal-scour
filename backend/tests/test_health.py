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


def test_plans_router_is_mounted() -> None:
    body = {"needs": [{"line_id": "atta", "product_key": "aashirvaad_select_atta_5kg", "qty": 1}]}
    res = TestClient(app).post("/api/v1/plans", json=body)
    assert res.status_code == 200
    assert res.json()["plans"][0]["label"] == "cheapest_now"


def test_integrity_error_maps_to_409() -> None:
    import asyncio

    from sqlalchemy.exc import IntegrityError

    from app.main import integrity_conflict

    res = asyncio.run(integrity_conflict(None, IntegrityError("x", None, Exception("dup"))))  # type: ignore[arg-type]
    assert res.status_code == 409


def test_web_app_served_with_spa_fallback(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import importlib

    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<!doctype html><title>DealScour</title>")
    (tmp_path / "assets" / "app.js").write_text("console.log(1)")
    (tmp_path / "manifest.webmanifest").write_text("{}")
    monkeypatch.setenv("DEALSCOUR_STATIC_DIR", str(tmp_path))
    import app.main as main_module

    reloaded = importlib.reload(main_module)
    try:
        c = TestClient(reloaded.app)
        assert "DealScour" in c.get("/").text
        assert "DealScour" in c.get("/plans/123").text  # client-side route
        assert c.get("/assets/app.js").text == "console.log(1)"
        assert c.get("/manifest.webmanifest").text == "{}"
        assert c.get("/../../etc/passwd").status_code in (200, 404)  # never escapes static_dir
        assert "root:" not in c.get("/%2e%2e/%2e%2e/etc/passwd").text
        assert c.get("/api/v1/health").json() == {"status": "ok"}
        assert c.get("/api/v1/nope").status_code == 404
    finally:
        monkeypatch.delenv("DEALSCOUR_STATIC_DIR")
        importlib.reload(main_module)


def test_importing_app_does_not_create_db(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import importlib

    monkeypatch.setenv("DEALSCOUR_DB_PATH", str(tmp_path / "nested" / "x.db"))
    import app.core.db as db_module
    import app.main as main_module

    importlib.reload(db_module)
    importlib.reload(main_module)
    assert not (tmp_path / "nested").exists()
    importlib.reload(db_module)
    importlib.reload(main_module)
