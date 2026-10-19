"""Lead-owned wiring: the radar router in the real app (CSRF + bearer) and the background loop."""

import dataclasses
import threading
from collections.abc import Generator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from app.core.config import Settings
from app.core.db import get_session
from app.core.extension_auth import issue_extension_token
from app.domain.models import RadarChannel, RadarPost
from app.main import app
from app.notify.base import Notifier
from app.radar.links import ResolvedLink
from app.radar.loop import run_radar_tick, setup_radar_loop

PEER = "-1001191090845"


@pytest.fixture
def main_client(engine: Engine) -> Generator[TestClient, None, None]:
    def override_get_session() -> Generator[Session, None, None]:
        with Session(engine) as s:
            yield s

    app.dependency_overrides[get_session] = override_get_session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _token_and_channel(engine: Engine) -> str:
    with Session(engine) as s:
        s.add(
            RadarChannel(
                household_id=1, peer_id=PEER, name="Offer Box", enabled=True, created_at=datetime.now(UTC)
            )
        )
        token, _ = issue_extension_token(s, 1, datetime.now(UTC))
        s.commit()
    return token


def _post(message_id: str) -> dict[str, object]:
    return {
        "peer_id": PEER,
        "message_id": message_id,
        "text": "Loot ₹99 : https://amzn.to/x",
        "links": ["https://amzn.to/x"],
        "posted_at": datetime.now(UTC).isoformat(),
    }


def test_radar_posts_in_the_real_app_need_bearer_and_csrf_header(
    main_client: TestClient, engine: Engine
) -> None:
    token = _token_and_channel(engine)
    auth = {"Authorization": f"Bearer {token}"}

    no_csrf = main_client.post(
        "/api/v1/radar/posts", json={"posts": [_post("1")]}, headers={**auth, "X-DealScour": "0"}
    )
    assert no_csrf.status_code == 403

    ok = main_client.post(
        "/api/v1/radar/posts", json={"posts": [_post("2")]}, headers={**auth, "X-DealScour": "1"}
    )
    assert ok.status_code == 200, ok.text

    bad_token = main_client.post(
        "/api/v1/radar/posts",
        json={"posts": [_post("3")]},
        headers={"Authorization": "Bearer nope", "X-DealScour": "1"},
    )
    assert bad_token.status_code == 401


class _NoResolve:
    def resolve(self, raw_url: str) -> ResolvedLink:
        return ResolvedLink(status="unsupported", ref=None, reason="unsupported_link")


class _QuietNotifier(Notifier):
    def send(self, text: str) -> bool:  # pragma: no cover - never reached for unsupported links
        return True


def test_radar_tick_finishes_pending_posts(main_client: TestClient, engine: Engine) -> None:
    token = _token_and_channel(engine)
    resp = main_client.post(
        "/api/v1/radar/posts",
        json={"posts": [_post("10")]},
        headers={"Authorization": f"Bearer {token}", "X-DealScour": "1"},
    )
    assert resp.status_code == 200, resp.text

    processed, _sent = run_radar_tick(
        engine, resolver=_NoResolve(), page_fetcher=lambda p, u: None, notifier=_QuietNotifier()
    )
    assert processed == 1
    with Session(engine) as s:
        post = s.exec(select(RadarPost).where(RadarPost.message_id == "10")).one()
        assert post.status == "done"
        assert post.verdict == "unsupported_link"


def test_radar_loop_starts_only_when_enabled(engine: Engine) -> None:
    class _State:
        pass

    class _App:
        state = _State()

    assert (
        setup_radar_loop(_App(), dataclasses.replace(Settings.from_env(), radar_enabled=False), engine)
        is None
    )
    assert not any(t.name == "dealscour-radar" for t in threading.enumerate())


def test_quiet_hours_use_india_time() -> None:
    from app.notify.base import is_quiet_hours, next_quiet_hours_end

    # 18:00 UTC = 23:30 IST: quiet. 03:00 UTC = 08:30 IST: not quiet. 23:30 UTC = 05:00 IST: quiet.
    assert is_quiet_hours(datetime(2026, 10, 19, 18, 0, tzinfo=UTC))
    assert not is_quiet_hours(datetime(2026, 10, 19, 3, 0, tzinfo=UTC))
    assert is_quiet_hours(datetime(2026, 10, 19, 23, 30, tzinfo=UTC))
    # Held at 23:30 IST on the 19th → sent at 07:00 IST on the 20th = 01:30 UTC on the 20th.
    assert next_quiet_hours_end(datetime(2026, 10, 19, 18, 0, tzinfo=UTC)) == datetime(
        2026, 10, 20, 1, 30, tzinfo=UTC
    )
    # Held at 05:00 IST on the 20th → 07:00 IST the same morning.
    assert next_quiet_hours_end(datetime(2026, 10, 19, 23, 30, tzinfo=UTC)) == datetime(
        2026, 10, 20, 1, 30, tzinfo=UTC
    )


@pytest.mark.parametrize(
    "url",
    [
        "https://user:pass@amzn.to/abc",
        "https://amzn.to:8443/abc",
        "https://user@www.amazon.in/dp/B09GNV7YZM",
        "https://www.amazon.in:444/dp/B09GNV7YZM",
    ],
)
def test_links_with_userinfo_or_port_are_refused(url: str) -> None:
    from app.radar.links import LinkResolver

    calls: list[str] = []

    def fake_fetch(u: str, max_bytes: int) -> tuple[int, dict[str, str], bytes]:
        calls.append(u)
        return 404, {}, b""

    res = LinkResolver(http_fetch=fake_fetch, sleep=lambda s: None).resolve(url)
    assert res.status == "unsupported"
    assert calls == []
