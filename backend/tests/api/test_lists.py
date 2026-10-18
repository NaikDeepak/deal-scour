from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.api.v1.lists import router as lists_router
from app.core.db import create_db_engine, get_session
from app.domain.models import Household, ShoppingList


def test_list_lifecycle_and_open_needs(client: TestClient) -> None:
    # 3. Lists: create -> appears in GET /lists with open_needs 0.
    res = client.post("/api/v1/lists", json={"name": "Weekly Groceries", "kind": "quick"})
    assert res.status_code == 201, res.text
    list_data = res.json()
    list_id = list_data["id"]
    assert list_data["name"] == "Weekly Groceries"
    assert list_data["kind"] == "quick"
    assert list_data["archived"] is False

    # GET /lists -> open_needs 0
    res = client.get("/api/v1/lists")
    assert res.status_code == 200
    lists = res.json()
    assert len(lists) == 1
    assert lists[0]["id"] == list_id
    assert lists[0]["open_needs"] == 0

    # Add 2 needs: one exact fortune_sunlite_oil_5l, one flexible sunflower_oil + "5L"
    res1 = client.post(
        f"/api/v1/lists/{list_id}/needs",
        json={"line_id": "oil1", "product_key": "fortune_sunlite_oil_5l", "qty": 1},
    )
    assert res1.status_code == 201, res1.text

    res2 = client.post(
        f"/api/v1/lists/{list_id}/needs",
        json={"line_id": "oil2", "family_key": "sunflower_oil", "quantity": "5L", "qty": 1},
    )
    assert res2.status_code == 201, res2.text

    # open_needs 2
    res = client.get("/api/v1/lists")
    assert res.status_code == 200
    lists = res.json()
    assert len(lists) == 1
    assert lists[0]["open_needs"] == 2

    # Archive -> hidden from GET /lists
    res = client.patch(f"/api/v1/lists/{list_id}", json={"archived": True})
    assert res.status_code == 200
    assert res.json()["archived"] is True

    res = client.get("/api/v1/lists")
    assert res.status_code == 200
    assert len(res.json()) == 0


def test_need_validation_and_line_id_uniqueness(client: TestClient) -> None:
    # 4. Need validation: both keys -> 422. Flexible without quantity -> 422. Unknown product -> 422.
    # Duplicate line_id in a list -> 409. The same line_id in another list -> OK.
    r_list1 = client.post("/api/v1/lists", json={"name": "List 1", "kind": "quick"})
    list1_id = r_list1.json()["id"]

    r_list2 = client.post("/api/v1/lists", json={"name": "List 2", "kind": "monthly"})
    list2_id = r_list2.json()["id"]

    # Both keys -> 422
    r = client.post(
        f"/api/v1/lists/{list1_id}/needs",
        json={
            "line_id": "item1",
            "product_key": "fortune_sunlite_oil_5l",
            "family_key": "sunflower_oil",
        },
    )
    assert r.status_code == 422

    # Flexible without quantity -> 422
    r = client.post(
        f"/api/v1/lists/{list1_id}/needs",
        json={"line_id": "item1", "family_key": "sunflower_oil"},
    )
    assert r.status_code == 422

    # Unknown product -> 422
    r = client.post(
        f"/api/v1/lists/{list1_id}/needs",
        json={"line_id": "item1", "product_key": "unknown_oil_xyz"},
    )
    assert r.status_code == 422

    # Valid need in list 1
    r = client.post(
        f"/api/v1/lists/{list1_id}/needs",
        json={"line_id": "item1", "product_key": "fortune_sunlite_oil_5l"},
    )
    assert r.status_code == 201

    # Duplicate line_id in list 1 -> 409
    r = client.post(
        f"/api/v1/lists/{list1_id}/needs",
        json={"line_id": "item1", "product_key": "fortune_sunlite_oil_5l"},
    )
    assert r.status_code == 409

    # Same line_id in list 2 -> OK (201)
    r = client.post(
        f"/api/v1/lists/{list2_id}/needs",
        json={"line_id": "item1", "product_key": "fortune_sunlite_oil_5l"},
    )
    assert r.status_code == 201


def test_need_patch_and_delete(client: TestClient) -> None:
    # 5. PATCH need status -> planned/bought. DELETE -> dropped (row still exists in GET /lists/{id}).
    # PATCH with an invalid combination -> 422.
    r_list = client.post("/api/v1/lists", json={"name": "List 1", "kind": "quick"})
    list_id = r_list.json()["id"]

    r_need = client.post(
        f"/api/v1/lists/{list_id}/needs",
        json={"line_id": "oil", "product_key": "fortune_sunlite_oil_5l", "qty": 1},
    )
    need_id = r_need.json()["id"]

    # PATCH status -> planned
    r = client.patch(f"/api/v1/needs/{need_id}", json={"status": "planned"})
    assert r.status_code == 200
    assert r.json()["status"] == "planned"

    # PATCH status -> bought
    r = client.patch(f"/api/v1/needs/{need_id}", json={"status": "bought"})
    assert r.status_code == 200
    assert r.json()["status"] == "bought"

    # PATCH with invalid combination (e.g. quantity on exact product) -> 422
    r = client.patch(f"/api/v1/needs/{need_id}", json={"quantity": "5L"})
    assert r.status_code == 422

    # DELETE -> dropped (status="dropped", 200)
    r = client.delete(f"/api/v1/needs/{need_id}")
    assert r.status_code == 200
    assert r.json()["status"] == "dropped"

    # Row still exists in GET /lists/{id}
    r = client.get(f"/api/v1/lists/{list_id}")
    assert r.status_code == 200
    data = r.json()
    assert len(data["needs"]) == 1
    assert data["needs"][0]["id"] == need_id
    assert data["needs"][0]["status"] == "dropped"


def test_household_isolation(client: TestClient, session: Session) -> None:
    # 6. 404 for another household's list: insert a household 2 + list directly in DB
    # -> GET /lists/{id} -> 404.
    h2 = Household(id=2, name="Other Home", pincode="400001")
    session.add(h2)
    session.commit()

    other_list = ShoppingList(household_id=2, name="Other Household List", kind="quick")
    session.add(other_list)
    session.commit()
    session.refresh(other_list)

    # GET /lists/{id} -> 404 for current household (id=1)
    r = client.get(f"/api/v1/lists/{other_list.id}")
    assert r.status_code == 404


def test_persistence_across_app_instances(tmp_path: Path) -> None:
    # 9. Persistence across app instances: create a list with app A on a temp DB file,
    # then build a new app/engine on the same file -> the list is there.
    db_file = tmp_path / "persistence_test.db"
    db_url = f"sqlite:///{db_file.resolve()}"

    from alembic import command
    from alembic.config import Config

    alembic_cfg = Config(str(Path(__file__).parent.parent.parent / "alembic.ini"))
    alembic_cfg.set_main_option("sqlalchemy.url", db_url)
    alembic_cfg.set_main_option(
        "script_location", str(Path(__file__).parent.parent.parent / "migrations")
    )
    command.upgrade(alembic_cfg, "head")

    engine_a = create_db_engine(db_file)
    app_a = FastAPI()
    app_a.include_router(lists_router, prefix="/api/v1")

    def get_session_a():
        with Session(engine_a) as s:
            yield s

    app_a.dependency_overrides[get_session] = get_session_a

    with TestClient(app_a) as client_a:
        res = client_a.post("/api/v1/lists", json={"name": "Persisted List", "kind": "monthly"})
        assert res.status_code == 201
        created_id = res.json()["id"]

    engine_a.dispose()

    # App B on the same DB file
    engine_b = create_db_engine(db_file)
    app_b = FastAPI()
    app_b.include_router(lists_router, prefix="/api/v1")

    def get_session_b():
        with Session(engine_b) as s:
            yield s

    app_b.dependency_overrides[get_session] = get_session_b

    with TestClient(app_b) as client_b:
        res = client_b.get(f"/api/v1/lists/{created_id}")
        assert res.status_code == 200
        assert res.json()["name"] == "Persisted List"

    engine_b.dispose()
