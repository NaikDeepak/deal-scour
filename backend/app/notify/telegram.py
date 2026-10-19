import logging
from collections.abc import Callable
from typing import Any

from app.notify.base import AlertPayload, Notifier, format_alert_text

logger = logging.getLogger(__name__)


def _default_telegram_post(url: str, payload: dict[str, Any]) -> tuple[int, str]:
    import httpx

    # Ensure httpx does not log the bot token URL into root/caplog
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    with httpx.Client(timeout=10.0) as client:
        resp = client.post(url, json=payload)
        return resp.status_code, resp.text


class TelegramNotifier(Notifier):
    def __init__(
        self,
        bot_token: str,
        chat_id: str,
        *,
        http_post: Callable[[str, dict[str, Any]], tuple[int, str]] = _default_telegram_post,
    ) -> None:
        self._bot_token = (bot_token or "").strip()
        self._chat_id = (chat_id or "").strip()
        self._http_post = http_post

    def send_alert(self, alert: AlertPayload) -> bool:
        if not self._bot_token or not self._chat_id:
            return False

        url = f"https://api.telegram.org/bot{self._bot_token}/sendMessage"
        payload: dict[str, Any] = {
            "chat_id": self._chat_id,
            "text": format_alert_text(alert),
            "disable_web_page_preview": False,
        }
        try:
            status_code, _body = self._http_post(url, payload)
            return status_code == 200
        except Exception as exc:
            safe_msg = str(exc).replace(self._bot_token, "[REDACTED]")
            logger.warning("Telegram sendMessage failed: %s", safe_msg)
            return False
