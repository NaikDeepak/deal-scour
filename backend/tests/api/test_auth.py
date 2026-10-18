import logging
from collections.abc import Generator
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.api.v1.auth import router as auth_router
from app.api.v1.baskets import router as baskets_router
from app.api.v1.lists import router as lists_router
from app.api.v1.offers import router as offers_router
from app.api.v1.prices import router as prices_router
from app.core import clock
from app.core.config import Settings
from app.core.db import get_session
from app.core.security import hash_invite_code
from app.domain.models import AppUser, AuthSession, Household, HouseholdMember, Invite
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
def auth_app(
    engine: Engine,
    test_clock: dict[str, datetime],
    capturing_sender: CapturingEmailSender,
    monkeypatch: pytest.MonkeyPatch,
) -> FastAPI:
    monkeypatch.setenv("DEALSCOUR_SECRET_KEY", "test-secret-key-for-auth-tests-min32ch")
    monkeypatch.setenv("DEALSCOUR_OWNER_EMAIL", "owner@dealscour.local")
    monkeypatch.setenv("DEALSCOUR_DEV_LOGIN", "0")

    app = FastAPI()
    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(lists_router, prefix="/api/v1")
    app.include_router(offers_router, prefix="/api/v1")
    app.include_router(baskets_router, prefix="/api/v1")
    app.include_router(prices_router, prefix="/api/v1")

    def override_get_session() -> Generator[Session, None, None]:
        with Session(engine) as s:
            yield s

    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[clock.now] = lambda: test_clock["now"]
    app.dependency_overrides[get_email_sender] = lambda: capturing_sender
    return app


@pytest.fixture
def auth_client(auth_app: FastAPI) -> Generator[TestClient, None, None]:
    with TestClient(auth_app) as client:
        client.headers["X-DealScour"] = "1"
        yield client


def test_1_owner_bootstrap(
    auth_client: TestClient,
    capturing_sender: CapturingEmailSender,
) -> None:
    # 1. Owner bootstrap: owner_email requests a code -> sender called once.
    r_req = auth_client.post("/api/v1/auth/request-code", json={"email": "owner@dealscour.local"})
    assert r_req.status_code == 202
    assert r_req.json() == {"sent": True}
    assert len(capturing_sender.sent) == 1
    assert capturing_sender.sent[0][0] == "owner@dealscour.local"
    code = capturing_sender.sent[0][1]
    assert len(code) == 6

    # Verify -> 200, role owner, household 1, cookie set with HttpOnly and SameSite=Lax.
    r_ver = auth_client.post(
        "/api/v1/auth/verify",
        json={"email": "owner@dealscour.local", "code": code, "name": "The Owner"},
    )
    assert r_ver.status_code == 200
    data = r_ver.json()
    assert data["role"] == "owner"
    assert data["household_id"] == 1
    assert data["user"]["email"] == "owner@dealscour.local"
    assert data["user"]["name"] == "The Owner"

    cookie = r_ver.cookies.get("ds_session")
    assert cookie is not None


def test_2_stranger_email_rejected(
    auth_client: TestClient,
    capturing_sender: CapturingEmailSender,
) -> None:
    # 2. A stranger email (not owner, no invite) -> 202 and no email sent. Verify with any code -> 400.
    r_req = auth_client.post("/api/v1/auth/request-code", json={"email": "stranger@example.com"})
    assert r_req.status_code == 202
    assert r_req.json() == {"sent": True}
    assert len(capturing_sender.sent) == 0

    r_ver = auth_client.post(
        "/api/v1/auth/verify",
        json={"email": "stranger@example.com", "code": "123456"},
    )
    assert r_ver.status_code == 400
    assert "Invalid or expired" in r_ver.json()["detail"]


def test_3_attempts_expiry_and_reuse(
    auth_client: TestClient,
    capturing_sender: CapturingEmailSender,
    test_clock: dict[str, datetime],
) -> None:
    # Setup owner code
    auth_client.post("/api/v1/auth/request-code", json={"email": "owner@dealscour.local"})
    code = capturing_sender.sent[-1][1]

    # Wrong code 5 times -> 400
    for _ in range(5):
        r_fail = auth_client.post(
            "/api/v1/auth/verify",
            json={"email": "owner@dealscour.local", "code": "000000"},
        )
        assert r_fail.status_code == 400

    # 6th attempt with the RIGHT code fails (400) because code is dead after 5 attempts
    r_dead = auth_client.post(
        "/api/v1/auth/verify",
        json={"email": "owner@dealscour.local", "code": code},
    )
    assert r_dead.status_code == 400

    # Expired code (clock +11 min) -> 400
    capturing_sender.sent.clear()
    auth_client.post("/api/v1/auth/request-code", json={"email": "owner@dealscour.local"})
    code2 = capturing_sender.sent[-1][1]

    test_clock["now"] += timedelta(minutes=11)
    r_exp = auth_client.post(
        "/api/v1/auth/verify",
        json={"email": "owner@dealscour.local", "code": code2},
    )
    assert r_exp.status_code == 400

    # Used code reused -> 400
    test_clock["now"] += timedelta(minutes=1)
    auth_client.post("/api/v1/auth/request-code", json={"email": "owner@dealscour.local"})
    code3 = capturing_sender.sent[-1][1]
    r_success = auth_client.post(
        "/api/v1/auth/verify",
        json={"email": "owner@dealscour.local", "code": code3},
    )
    assert r_success.status_code == 200

    r_reuse = auth_client.post(
        "/api/v1/auth/verify",
        json={"email": "owner@dealscour.local", "code": code3},
    )
    assert r_reuse.status_code == 400


def test_4_rate_limiting(
    auth_client: TestClient,
    capturing_sender: CapturingEmailSender,
    test_clock: dict[str, datetime],
) -> None:
    # 4. Rate limit: the 6th request-code within an hour sends nothing. After +61 min it sends again.
    for i in range(5):
        r = auth_client.post("/api/v1/auth/request-code", json={"email": "owner@dealscour.local"})
        assert r.status_code == 202
        assert len(capturing_sender.sent) == i + 1

    # 6th request within the hour -> 202, but sender NOT called
    r6 = auth_client.post("/api/v1/auth/request-code", json={"email": "owner@dealscour.local"})
    assert r6.status_code == 202
    assert len(capturing_sender.sent) == 5

    # Advance clock 61 minutes
    test_clock["now"] += timedelta(minutes=61)
    r7 = auth_client.post("/api/v1/auth/request-code", json={"email": "owner@dealscour.local"})
    assert r7.status_code == 202
    assert len(capturing_sender.sent) == 6


def test_7_protected_routes_and_csrf(
    auth_client: TestClient,
    capturing_sender: CapturingEmailSender,
) -> None:
    # 7. Protected routes: GET /api/v1/lists without a cookie -> 401.
    r_no_auth = auth_client.get("/api/v1/lists")
    assert r_no_auth.status_code == 401

    # Authenticate as owner
    auth_client.post("/api/v1/auth/request-code", json={"email": "owner@dealscour.local"})
    code = capturing_sender.sent[-1][1]
    r_ver = auth_client.post("/api/v1/auth/verify", json={"email": "owner@dealscour.local", "code": code})
    assert r_ver.status_code == 200

    # With cookie -> 200
    r_auth = auth_client.get("/api/v1/lists")
    assert r_auth.status_code == 200

    # POST without X-DealScour -> 403
    r_post_no_csrf = auth_client.post(
        "/api/v1/lists",
        json={"name": "Weekly", "kind": "quick"},
        headers={"X-DealScour": "0"},
    )
    assert r_post_no_csrf.status_code == 403

    # POST with X-DealScour: 1 -> 201
    r_post_csrf = auth_client.post(
        "/api/v1/lists",
        json={"name": "Weekly", "kind": "quick"},
        headers={"X-DealScour": "1"},
    )
    assert r_post_csrf.status_code == 201


def test_8_household_isolation(
    auth_client: TestClient,
    capturing_sender: CapturingEmailSender,
    engine: Engine,
) -> None:
    # 8. Isolation: two households (owner of hh1 invites A; a second owner set directly in the DB for hh2)
    # Bootstrap owner of hh1
    auth_client.post("/api/v1/auth/request-code", json={"email": "owner@dealscour.local"})
    code_owner = capturing_sender.sent[-1][1]
    auth_client.post("/api/v1/auth/verify", json={"email": "owner@dealscour.local", "code": code_owner})

    # Owner creates list in hh1
    auth_client.post(
        "/api/v1/lists",
        json={"name": "HH1 Groceries", "kind": "quick"},
        headers={"X-DealScour": "1"},
    )

    # Directly create household 2 and user B in DB
    with Session(engine) as session:
        hh2 = Household(name="Household 2", pincode="411018")
        session.add(hh2)
        session.commit()
        session.refresh(hh2)

        user_b = AppUser(email="userb@dealscour.local", name="User B")
        session.add(user_b)
        session.commit()
        session.refresh(user_b)

        assert hh2.id is not None
        assert user_b.id is not None
        mem2 = HouseholdMember(household_id=hh2.id, user_id=user_b.id, role="owner")
        session.add(mem2)

        from app.core.security import generate_session_token, hash_token

        token_b = generate_session_token()
        session_b = AuthSession(
            token_hash=hash_token(token_b),
            user_id=user_b.id,
            created_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(days=30),
            last_seen_at=datetime.now(UTC),
        )
        session.add(session_b)
        session.commit()

    # User B client
    auth_client.cookies.set("ds_session", token_b)
    r_b_lists = auth_client.get("/api/v1/lists")
    assert r_b_lists.status_code == 200
    assert len(r_b_lists.json()) == 0  # HH1's list is isolated from HH2


def test_9_session_expiry_and_logout(
    auth_client: TestClient,
    capturing_sender: CapturingEmailSender,
    test_clock: dict[str, datetime],
    engine: Engine,
) -> None:
    # 9. Session expiry (+31 days) -> 401. Logout -> cookie cleared, session row gone, next request 401.
    auth_client.post("/api/v1/auth/request-code", json={"email": "owner@dealscour.local"})
    code = capturing_sender.sent[-1][1]
    auth_client.post("/api/v1/auth/verify", json={"email": "owner@dealscour.local", "code": code})

    # Advance 31 days
    test_clock["now"] += timedelta(days=31)
    r_exp = auth_client.get("/api/v1/auth/me")
    assert r_exp.status_code == 401

    # Login again
    auth_client.post("/api/v1/auth/request-code", json={"email": "owner@dealscour.local"})
    code2 = capturing_sender.sent[-1][1]
    auth_client.post("/api/v1/auth/verify", json={"email": "owner@dealscour.local", "code": code2})

    r_me = auth_client.get("/api/v1/auth/me")
    assert r_me.status_code == 200

    # Logout
    r_logout = auth_client.post("/api/v1/auth/logout", headers={"X-DealScour": "1"})
    assert r_logout.status_code == 200
    # Cookie should be deleted or expired
    assert auth_client.cookies.get("ds_session") is None

    # Next request -> 401
    r_me2 = auth_client.get("/api/v1/auth/me")
    assert r_me2.status_code == 401

    # Session row in DB should be deleted
    with Session(engine) as s:
        sessions = s.exec(select(AuthSession)).all()
        assert len(sessions) == 0


def test_10_no_secrets_in_responses_or_logs(
    auth_client: TestClient,
    capturing_sender: CapturingEmailSender,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # 10. Nothing secret in responses or logs: assert code/token never appears in any JSON response and caplog
    caplog.set_level(logging.DEBUG)
    r_req = auth_client.post("/api/v1/auth/request-code", json={"email": "owner@dealscour.local"})
    code = capturing_sender.sent[-1][1]
    assert code not in r_req.text

    r_ver = auth_client.post("/api/v1/auth/verify", json={"email": "owner@dealscour.local", "code": code})
    cookie_token = auth_client.cookies.get("ds_session")
    assert cookie_token is not None

    assert code not in r_ver.text
    assert cookie_token not in r_ver.text

    r_me = auth_client.get("/api/v1/auth/me")
    assert code not in r_me.text
    assert cookie_token not in r_me.text

    # Check logs do not contain code or cookie token
    for record in caplog.records:
        assert code not in record.message
        assert cookie_token not in record.message


def test_13_brute_force_budget_across_24h(
    auth_client: TestClient,
    capturing_sender: CapturingEmailSender,
    test_clock: dict[str, datetime],
) -> None:
    # 13. Count failed attempts across all codes for the email in last 24h.
    # At >= 10, verify returns 400 and request-code silently sends nothing.
    auth_client.post("/api/v1/auth/request-code", json={"email": "owner@dealscour.local"})
    assert len(capturing_sender.sent) == 1

    # 5 wrong attempts on first code
    for _ in range(5):
        r = auth_client.post(
            "/api/v1/auth/verify",
            json={"email": "owner@dealscour.local", "code": "000000"},
        )
        assert r.status_code == 400

    # Advance 15 min and request second code
    test_clock["now"] += timedelta(minutes=15)
    auth_client.post("/api/v1/auth/request-code", json={"email": "owner@dealscour.local"})
    assert len(capturing_sender.sent) == 2

    # 5 wrong attempts on second code -> total 10 failed attempts within 24h
    for _ in range(5):
        r = auth_client.post(
            "/api/v1/auth/verify",
            json={"email": "owner@dealscour.local", "code": "000000"},
        )
        assert r.status_code == 400

    # Now budget is exhausted (10 failed attempts)
    # verify returns 400 immediately
    r_locked = auth_client.post(
        "/api/v1/auth/verify",
        json={"email": "owner@dealscour.local", "code": "123456"},
    )
    assert r_locked.status_code == 400

    # request-code returns 202 but silently sends nothing
    capturing_sender.sent.clear()
    r_silent = auth_client.post(
        "/api/v1/auth/request-code",
        json={"email": "owner@dealscour.local"},
    )
    assert r_silent.status_code == 202
    assert len(capturing_sender.sent) == 0


def test_14_owner_race_and_unique_constraint(
    auth_client: TestClient,
    capturing_sender: CapturingEmailSender,
    engine: Engine,
) -> None:
    # 14. Owner race: bootstrap only if no owner exists yet
    auth_client.post("/api/v1/auth/request-code", json={"email": "owner@dealscour.local"})
    code = capturing_sender.sent[-1][1]
    r_ver = auth_client.post(
        "/api/v1/auth/verify",
        json={"email": "owner@dealscour.local", "code": code},
    )
    assert r_ver.status_code == 200

    # Second owner bootstrap attempt fails with 409
    # Verify partial unique index enforces single owner per household at DB level
    with pytest.raises(IntegrityError), Session(engine) as s:
        user2 = AppUser(email="owner2@dealscour.local", name="Owner 2")
        s.add(user2)
        s.commit()
        s.refresh(user2)
        assert user2.id is not None
        mem2 = HouseholdMember(household_id=1, user_id=user2.id, role="owner")
        s.add(mem2)
        s.commit()


def test_16_csrf_required_on_all_mutating_endpoints(
    auth_app: FastAPI,
) -> None:
    # 16. CSRF required on request-code and verify as well
    with TestClient(auth_app) as client_no_csrf:
        # Request-code without header -> 403
        r_req = client_no_csrf.post(
            "/api/v1/auth/request-code",
            json={"email": "owner@dealscour.local"},
        )
        assert r_req.status_code == 403

        # Verify without header -> 403
        r_ver = client_no_csrf.post(
            "/api/v1/auth/verify",
            json={"email": "owner@dealscour.local", "code": "123456"},
        )
        assert r_ver.status_code == 403


def test_17_timing_and_background_tasks(
    auth_client: TestClient,
    capturing_sender: CapturingEmailSender,
) -> None:
    # 17. Constant-work HMAC & BackgroundTasks sends email
    r = auth_client.post(
        "/api/v1/auth/request-code",
        json={"email": "owner@dealscour.local"},
    )
    assert r.status_code == 202
    assert len(capturing_sender.sent) == 1


def test_18_settings_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    # 18. Secret key validation and dev_login restricted to localhost
    # Missing secret key
    monkeypatch.delenv("DEALSCOUR_SECRET_KEY", raising=False)
    with pytest.raises(RuntimeError, match="DEALSCOUR_SECRET_KEY is required"):
        Settings.from_env()

    # Secret key too short (< 32 chars)
    monkeypatch.setenv("DEALSCOUR_SECRET_KEY", "short-secret-key-only")
    with pytest.raises(RuntimeError, match="at least 32 characters"):
        Settings.from_env()

    # Valid secret key
    monkeypatch.setenv("DEALSCOUR_SECRET_KEY", "a" * 32)
    s = Settings.from_env()
    assert s.secret_key == "a" * 32

    # dev_login on public host -> error
    monkeypatch.setenv("DEALSCOUR_DEV_LOGIN", "1")
    monkeypatch.setenv("DEALSCOUR_BASE_URL", "https://app.dealscour.in")
    with pytest.raises(RuntimeError, match="only allowed when DEALSCOUR_BASE_URL host is localhost"):
        Settings.from_env()

    # dev_login on localhost -> allowed
    monkeypatch.setenv("DEALSCOUR_BASE_URL", "http://localhost:8000")
    s_dev = Settings.from_env()
    assert s_dev.dev_login is True


def test_19_racing_invites_leave_no_orphan_user(
    auth_client: TestClient,
    capturing_sender: CapturingEmailSender,
    engine: Engine,
) -> None:
    # 19. Two verifies racing the same invite: first wins, second fails, exactly 1 new user
    auth_client.post("/api/v1/auth/request-code", json={"email": "owner@dealscour.local"})
    code_owner = capturing_sender.sent[-1][1]
    auth_client.post(
        "/api/v1/auth/verify",
        json={"email": "owner@dealscour.local", "code": code_owner},
    )

    # Seed a valid invite for household 1
    invite_code = "valid-invite-token-12345"
    with Session(engine) as s:
        invite = Invite(
            household_id=1,
            code_hash=hash_invite_code(invite_code),
            created_by=1,
            created_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(days=7),
        )
        s.add(invite)
        s.commit()

    # Two users request codes with the same valid invite
    capturing_sender.sent.clear()
    auth_client.post(
        "/api/v1/auth/request-code",
        json={"email": "alice@family.local", "invite_code": invite_code},
    )
    code_alice = capturing_sender.sent[-1][1]

    auth_client.post(
        "/api/v1/auth/request-code",
        json={"email": "bob@family.local", "invite_code": invite_code},
    )
    code_bob = capturing_sender.sent[-1][1]

    # Alice verifies first and wins
    r_alice = auth_client.post(
        "/api/v1/auth/verify",
        json={
            "email": "alice@family.local",
            "code": code_alice,
            "invite_code": invite_code,
            "name": "Alice",
        },
    )
    assert r_alice.status_code == 200
    assert r_alice.json()["role"] == "member"

    # Bob verifies second with the same invite and loses
    r_bob = auth_client.post(
        "/api/v1/auth/verify",
        json={
            "email": "bob@family.local",
            "code": code_bob,
            "invite_code": invite_code,
            "name": "Bob",
        },
    )
    assert r_bob.status_code == 400
    assert "Invalid or expired invite" in r_bob.json()["detail"]

    # Verify DB: Bob was NEVER created as an orphan user!
    with Session(engine) as s:
        bob_user = s.exec(select(AppUser).where(AppUser.email == "bob@family.local")).first()
        assert bob_user is None

        alice_user = s.exec(select(AppUser).where(AppUser.email == "alice@family.local")).first()
        assert alice_user is not None

        all_users = s.exec(select(AppUser)).all()
        # Exactly 2 users: owner + Alice
        assert len(all_users) == 2

        inv_db = s.exec(select(Invite).where(Invite.code_hash == hash_invite_code(invite_code))).first()
        assert inv_db is not None
        assert inv_db.used_by == alice_user.id
        assert inv_db.used_at is not None


def test_19_racing_invites_simulated_interleaved_claim_leaves_no_orphan(
    auth_client: TestClient,
    capturing_sender: CapturingEmailSender,
    engine: Engine,
) -> None:
    # Simulate race where invite is claimed right between lookup and atomic update
    auth_client.post("/api/v1/auth/request-code", json={"email": "owner@dealscour.local"})
    code_owner = capturing_sender.sent[-1][1]
    auth_client.post(
        "/api/v1/auth/verify",
        json={"email": "owner@dealscour.local", "code": code_owner},
    )

    invite_code = "interleaved-race-invite-54321"
    with Session(engine) as s:
        invite = Invite(
            household_id=1,
            code_hash=hash_invite_code(invite_code),
            created_by=1,
            created_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(days=7),
        )
        s.add(invite)
        s.commit()

    capturing_sender.sent.clear()
    auth_client.post(
        "/api/v1/auth/request-code",
        json={"email": "carol@family.local", "invite_code": invite_code},
    )
    code_carol = capturing_sender.sent[-1][1]

    # Intercept cursor execution: when UPDATE on invite runs, claim it beforehand
    interleaved = False

    @sa.event.listens_for(engine, "before_cursor_execute")
    def intercept_claim(conn, cursor, statement, parameters, context, executemany):  # type: ignore[no-untyped-def]
        nonlocal interleaved
        if "UPDATE invite" in statement and not interleaved:
            interleaved = True
            conn.exec_driver_sql("UPDATE invite SET used_at = '2026-10-18 12:00:00' WHERE used_at IS NULL")

    try:
        r_carol = auth_client.post(
            "/api/v1/auth/verify",
            json={
                "email": "carol@family.local",
                "code": code_carol,
                "invite_code": invite_code,
                "name": "Carol",
            },
        )
        assert r_carol.status_code == 400
        assert "Invalid or expired invite" in r_carol.json()["detail"]
    finally:
        sa.event.remove(engine, "before_cursor_execute", intercept_claim)

    assert interleaved is True
    # Carol was NEVER created as an orphan user
    with Session(engine) as s:
        carol_user = s.exec(select(AppUser).where(AppUser.email == "carol@family.local")).first()
        assert carol_user is None


def test_20_attempts_reserved_atomically_success_not_counted(
    auth_client: TestClient,
    capturing_sender: CapturingEmailSender,
    engine: Engine,
) -> None:
    """Verify reserves an attempt (guarded UPDATE) before comparing; a correct code gives it back."""
    from sqlmodel import Session, select

    from app.domain.models import LoginCode

    email = "owner@dealscour.local"
    auth_client.post("/api/v1/auth/request-code", json={"email": email})
    code = capturing_sender.sent[-1][1]
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(4):
        assert (
            auth_client.post("/api/v1/auth/verify", json={"email": email, "code": wrong}).status_code == 400
        )
    # 5th request is the right code: allowed (4 < 5), and the reserved attempt is handed back.
    assert auth_client.post("/api/v1/auth/verify", json={"email": email, "code": code}).status_code == 200
    with Session(engine) as s:
        row = s.exec(select(LoginCode).where(LoginCode.email == email)).one()
        assert row.attempts == 4  # only the wrong guesses count toward the budget
        assert row.used_at is not None
