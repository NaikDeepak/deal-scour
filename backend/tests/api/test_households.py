from collections.abc import Generator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlmodel import Session

from app.api.v1.auth import router as auth_router
from app.api.v1.households import router as households_router
from app.core import clock
from app.core.db import get_session
from app.notify.email import EmailSender, get_email_sender


class CapturingEmailSender(EmailSender):
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def send_login_code(self, email: str, code: str) -> None:
        self.sent.append((email, code))


@pytest.fixture
def test_clock() -> Generator[dict[str, datetime], None, None]:
    state = {"now": datetime(2026, 10, 18, 12, 0, 0, tzinfo=UTC)}
    yield state


@pytest.fixture
def capturing_sender() -> CapturingEmailSender:
    return CapturingEmailSender()


@pytest.fixture
def household_app(
    engine: Engine,
    test_clock: dict[str, datetime],
    capturing_sender: CapturingEmailSender,
    monkeypatch: pytest.MonkeyPatch,
) -> FastAPI:
    monkeypatch.setenv("DEALSCOUR_SECRET_KEY", "test-secret-key-for-household-tests-32")
    monkeypatch.setenv("DEALSCOUR_OWNER_EMAIL", "owner@dealscour.local")
    monkeypatch.setenv("DEALSCOUR_DEV_LOGIN", "0")

    app = FastAPI()
    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(households_router, prefix="/api/v1")

    def override_get_session() -> Generator[Session, None, None]:
        with Session(engine) as s:
            yield s

    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[clock.now] = lambda: test_clock["now"]
    app.dependency_overrides[get_email_sender] = lambda: capturing_sender
    return app


@pytest.fixture
def client(household_app: FastAPI) -> Generator[TestClient, None, None]:
    with TestClient(household_app) as c:
        yield c


def test_5_invite_flow_and_reuse_and_expiry(
    client: TestClient,
    capturing_sender: CapturingEmailSender,
    test_clock: dict[str, datetime],
) -> None:
    # 5. Invite: owner creates an invite -> a new email requests with invite_code
    # -> verify with name -> role member of the same household
    # Bootstrap owner
    client.post("/api/v1/auth/request-code", json={"email": "owner@dealscour.local"})
    code_owner = capturing_sender.sent[-1][1]
    client.post("/api/v1/auth/verify", json={"email": "owner@dealscour.local", "code": code_owner})

    # Owner creates invite
    r_inv = client.post("/api/v1/households/invites", headers={"X-DealScour": "1"})
    assert r_inv.status_code in (200, 201)
    inv_data = r_inv.json()
    invite_code = inv_data["invite_code"]
    assert len(invite_code) >= 10

    # New email requests code with invite_code
    r_req = client.post(
        "/api/v1/auth/request-code",
        json={"email": "alice@family.local", "invite_code": invite_code},
    )
    assert r_req.status_code == 202
    assert r_req.json() == {"sent": True}
    alice_code = capturing_sender.sent[-1][1]

    # Verify with name -> role member of the same household
    r_ver = client.post(
        "/api/v1/auth/verify",
        json={
            "email": "alice@family.local",
            "code": alice_code,
            "invite_code": invite_code,
            "name": "Alice",
        },
    )
    assert r_ver.status_code == 200
    alice_data = r_ver.json()
    assert alice_data["role"] == "member"
    assert alice_data["household_id"] == 1
    assert alice_data["user"]["name"] == "Alice"

    # Reusing the same invite for another email -> no code sent (202) and verify 400
    capturing_sender.sent.clear()
    r_req2 = client.post(
        "/api/v1/auth/request-code",
        json={"email": "bob@family.local", "invite_code": invite_code},
    )
    assert r_req2.status_code == 202
    assert len(capturing_sender.sent) == 0

    r_ver2 = client.post(
        "/api/v1/auth/verify",
        json={"email": "bob@family.local", "code": "123456", "invite_code": invite_code},
    )
    assert r_ver2.status_code == 400

    # Expired invite (+8 days) -> same
    # Create another invite as owner
    client.cookies.clear()
    client.post("/api/v1/auth/request-code", json={"email": "owner@dealscour.local"})
    code_owner2 = capturing_sender.sent[-1][1]
    client.post("/api/v1/auth/verify", json={"email": "owner@dealscour.local", "code": code_owner2})

    r_inv2 = client.post("/api/v1/households/invites", headers={"X-DealScour": "1"})
    inv2_code = r_inv2.json()["invite_code"]

    # Advance clock +8 days
    test_clock["now"] += timedelta(days=8)
    capturing_sender.sent.clear()
    r_exp_req = client.post(
        "/api/v1/auth/request-code",
        json={"email": "charlie@family.local", "invite_code": inv2_code},
    )
    assert r_exp_req.status_code == 202
    assert len(capturing_sender.sent) == 0


def test_6_member_permissions_and_removal(
    client: TestClient,
    capturing_sender: CapturingEmailSender,
    engine: Engine,
) -> None:
    # 6. Non-owner creating an invite -> 403. Removing a member deletes their sessions (next request -> 401).
    # Owner login
    client.post("/api/v1/auth/request-code", json={"email": "owner@dealscour.local"})
    code_owner = capturing_sender.sent[-1][1]
    client.post("/api/v1/auth/verify", json={"email": "owner@dealscour.local", "code": code_owner})

    # Owner creates invite
    r_inv = client.post("/api/v1/households/invites", headers={"X-DealScour": "1"})
    invite_code = r_inv.json()["invite_code"]

    # Alice joins as member
    client.post(
        "/api/v1/auth/request-code",
        json={"email": "alice@family.local", "invite_code": invite_code},
    )
    code_alice = capturing_sender.sent[-1][1]
    client.post(
        "/api/v1/auth/verify",
        json={"email": "alice@family.local", "code": code_alice, "invite_code": invite_code, "name": "Alice"},
    )
    alice_token = client.cookies.get("ds_session")

    # Alice tries to create invite -> 403
    r_alice_inv = client.post("/api/v1/households/invites", headers={"X-DealScour": "1"})
    assert r_alice_inv.status_code == 403

    # Switch back to owner
    client.cookies.clear()
    client.post("/api/v1/auth/request-code", json={"email": "owner@dealscour.local"})
    code_owner2 = capturing_sender.sent[-1][1]
    r_owner_ver = client.post(
        "/api/v1/auth/verify",
        json={"email": "owner@dealscour.local", "code": code_owner2},
    )
    owner_user_id = r_owner_ver.json()["user"]["id"]

    # Check members list
    r_members = client.get("/api/v1/households/members")
    assert r_members.status_code == 200
    members = r_members.json()
    assert len(members) == 2
    alice_entry = next(m for m in members if m["email"] == "alice@family.local")
    alice_user_id = alice_entry["user_id"]

    # Owner cannot remove themselves -> 400
    r_del_self = client.delete(
        f"/api/v1/households/members/{owner_user_id}",
        headers={"X-DealScour": "1"},
    )
    assert r_del_self.status_code == 400

    # Owner removes Alice
    r_del = client.delete(
        f"/api/v1/households/members/{alice_user_id}",
        headers={"X-DealScour": "1"},
    )
    assert r_del.status_code == 200

    # Alice's session was deleted; her next request -> 401
    client.cookies.set("ds_session", alice_token)
    r_alice_me = client.get("/api/v1/auth/me")
    assert r_alice_me.status_code == 401
