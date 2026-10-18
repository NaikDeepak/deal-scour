from fastapi.testclient import TestClient


def test_offer_lifecycle_validation_and_archival(client: TestClient) -> None:
    # 7. Offers: POST valid flat offer -> 201. GET shows it.
    valid_offer = {
        "code": "A1",
        "platform": "amazon",
        "kind": "flat",
        "min_order_paise": 50000,
        "value_paise": 5000,
        "uses_left": 2,
        "stack_group": "platform_coupon",
        "value_type": "cash",
    }
    r = client.post("/api/v1/offers", json=valid_offer)
    assert r.status_code == 201, r.text
    created = r.json()
    assert created["code"] == "A1"
    offer_id = created["id"]

    # GET shows it
    r = client.get("/api/v1/offers")
    assert r.status_code == 200
    offers = r.json()
    assert any(o["code"] == "A1" for o in offers)

    # POST same code again -> 409
    r = client.post("/api/v1/offers", json=valid_offer)
    assert r.status_code == 409

    # POST kind: flat, value_paise: 0 -> 422
    invalid_flat = dict(valid_offer)
    invalid_flat["code"] = "A2"
    invalid_flat["value_paise"] = 0
    r = client.post("/api/v1/offers", json=invalid_flat)
    assert r.status_code == 422

    # Tiered with malformed tiers -> 422
    invalid_tiered = {
        "code": "T_BAD",
        "platform": "amazon",
        "kind": "tiered",
        "tiers": [[1000, 200], [500, 100]],  # Not strictly increasing
    }
    r = client.post("/api/v1/offers", json=invalid_tiered)
    assert r.status_code == 422

    # Archive offer -> POST /offers/{id}/archive
    r = client.post(f"/api/v1/offers/{offer_id}/archive")
    assert r.status_code == 200
    assert r.json()["archived"] is True

    # Hidden by default from GET /offers
    r = client.get("/api/v1/offers")
    assert r.status_code == 200
    assert not any(o["code"] == "A1" for o in r.json())

    # Shown with include_archived=true
    r = client.get("/api/v1/offers?include_archived=true")
    assert r.status_code == 200
    assert any(o["code"] == "A1" for o in r.json())

    # After archiving, the code can be reused
    r = client.post("/api/v1/offers", json=valid_offer)
    assert r.status_code == 201


def test_offer_patch(client: TestClient) -> None:
    valid_offer = {
        "code": "PATCH1",
        "platform": "blinkit",
        "kind": "flat",
        "min_order_paise": 30000,
        "value_paise": 3000,
        "uses_left": 1,
    }
    r = client.post("/api/v1/offers", json=valid_offer)
    assert r.status_code == 201
    offer_id = r.json()["id"]

    # PATCH /offers/{id} (uses_left, valid_to, note, archived)
    r = client.patch(
        f"/api/v1/offers/{offer_id}",
        json={
            "uses_left": 5,
            "valid_to": "2026-12-31",
            "note": "Updated note",
            "archived": False,
        },
    )
    assert r.status_code == 200
    updated = r.json()
    assert updated["uses_left"] == 5
    assert updated["valid_to"] == "2026-12-31"
    assert updated["note"] == "Updated note"
