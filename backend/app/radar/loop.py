"""Background loop for the deal radar: process pending posts and flush held alerts every 60 s.

Started from `app/main.py` only when DEALSCOUR_RADAR=1, like the price fetcher (ADR-004).
"""

import logging
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.engine import Engine
from sqlmodel import Session

from app.core.config import Settings
from app.notify.base import Notifier, send_due_alerts
from app.notify.telegram import TelegramNotifier
from app.radar.links import _DEFAULT_RESOLVER
from app.radar.process import LinkResolving, PageFetcher, default_page_fetcher, process_pending_posts

logger = logging.getLogger(__name__)

INTERVAL_SECONDS = 60.0
_LOOP_STARTED = threading.Event()


def run_radar_tick(
    engine: Engine,
    *,
    resolver: LinkResolving,
    page_fetcher: PageFetcher,
    notifier: Notifier,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> tuple[int, int]:
    """One pass: finish up to 10 pending posts, then send held alerts that are due.

    Returns (processed, sent).
    """
    with Session(engine) as session:
        processed = process_pending_posts(
            session, now(), resolver=resolver, page_fetcher=page_fetcher, notifier=notifier
        )
        sent = send_due_alerts(session, now(), notifier)
        session.commit()
    return processed, sent


def run_radar_worker(engine: Engine, settings: Settings, stop_event: threading.Event) -> None:
    notifier = TelegramNotifier(bot_token=settings.telegram_bot_token, chat_id=settings.telegram_chat_id)
    try:
        while not stop_event.wait(timeout=INTERVAL_SECONDS):
            try:
                run_radar_tick(
                    engine, resolver=_DEFAULT_RESOLVER, page_fetcher=default_page_fetcher, notifier=notifier
                )
            except Exception:
                # One bad pass must not kill the loop; the error is logged without post text or tokens.
                logger.exception("Radar pass failed")
    finally:
        # Let a later app start in the same process start the loop again.
        _LOOP_STARTED.clear()


def setup_radar_loop(app: Any, settings: Settings, engine: Engine | None = None) -> threading.Event | None:
    """Start the single radar loop when DEALSCOUR_RADAR=1. Returns the stop event (or None)."""
    if not settings.radar_enabled or engine is None or _LOOP_STARTED.is_set():
        return None
    _LOOP_STARTED.set()
    app.state.radar_loop_registered = True
    stop = threading.Event()
    threading.Thread(
        target=run_radar_worker, args=(engine, settings, stop), name="dealscour-radar", daemon=True
    ).start()
    logger.info("Deal radar enabled: processing Telegram posts every %ss", int(INTERVAL_SECONDS))
    return stop
