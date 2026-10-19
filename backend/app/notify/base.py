import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo

from sqlmodel import Session, select

from app.core.money import Paise
from app.domain.catalog import to_utc
from app.domain.models import RadarAlert

_REASON_LABELS = {
    "below_target": "Below target price",
    "30d_low": "At 30-day low",
    "under_avg": "≥15% under 30-day average",
    "beats_family_best": "≥10% below best price in family",
}


@dataclass(frozen=True)
class AlertPayload:
    title: str
    price_paise: Paise
    reasons: list[str]
    url: str
    platform: str = ""
    pack_label: str | None = None


class Notifier(Protocol):
    def send_alert(self, alert: AlertPayload) -> bool: ...


def format_rupees(paise: Paise) -> str:
    rupees = paise // 100
    rem = paise % 100
    s = f"{rupees:,}"
    if rem:
        return f"₹{s}.{rem:02d}"
    return f"₹{s}"


def format_alert_text(alert: AlertPayload) -> str:
    why_parts = [_REASON_LABELS.get(r, r) for r in alert.reasons]
    why_str = ", ".join(why_parts) if why_parts else "Deal alert"
    price_str = format_rupees(alert.price_paise)
    return f"DealScour Alert: {alert.title}\nPrice: {price_str}\nWhy: {why_str}\n{alert.url}"


# Quiet hours are the owner's local hours (Pune), not UTC.
LOCAL_TZ = ZoneInfo("Asia/Kolkata")


def is_quiet_hours(now_dt: datetime, quiet_start: int = 23, quiet_end: int = 7) -> bool:
    if quiet_start == quiet_end:
        return False
    h = to_utc(now_dt).astimezone(LOCAL_TZ).hour
    if quiet_start > quiet_end:
        return h >= quiet_start or h < quiet_end
    return quiet_start <= h < quiet_end


def next_quiet_hours_end(now_dt: datetime, quiet_start: int = 23, quiet_end: int = 7) -> datetime:
    """When held alerts may go out: the next quiet_end o'clock in local time, returned in UTC."""
    local = to_utc(now_dt).astimezone(LOCAL_TZ)
    end = local.replace(hour=quiet_end, minute=0, second=0, microsecond=0)
    if local.hour >= quiet_start and quiet_start > quiet_end:
        end += timedelta(days=1)
    return end.astimezone(UTC)


def record_and_dispatch_alert(
    *,
    session: Session,
    household_id: int,
    now_dt: datetime,
    product_key: str,
    platform: str,
    sku: str,
    title: str,
    url: str,
    price_paise: Paise,
    reasons: list[str],
    notifier: Notifier,
    post_id: int | None = None,
    quiet_start: int = 23,
    quiet_end: int = 7,
    daily_cap: int = 10,
) -> RadarAlert | None:
    """Apply 24h (product, price) dedupe, daily cap, and quiet hours, then record RadarAlert."""
    now_utc = to_utc(now_dt)
    since_24h = now_utc - timedelta(hours=24)

    existing_alerts = session.exec(
        select(RadarAlert).where(RadarAlert.household_id == household_id)
    ).all()
    recent_24h = [a for a in existing_alerts if to_utc(a.created_at) >= since_24h]

    # 1. Dedupe: one alert per (product, price) per 24h
    for a in recent_24h:
        if a.product_key == product_key and a.price_paise == price_paise:
            return None

    # 2. Daily cap: max N alerts per day (24h window)
    if len(recent_24h) >= daily_cap:
        return None

    payload = AlertPayload(
        title=title,
        price_paise=price_paise,
        reasons=reasons,
        url=url,
        platform=platform,
    )

    if is_quiet_hours(now_dt, quiet_start, quiet_end):
        scheduled = next_quiet_hours_end(now_dt, quiet_start, quiet_end)
        alert = RadarAlert(
            household_id=household_id,
            post_id=post_id,
            product_key=product_key,
            platform=platform,
            sku=sku,
            title=title,
            url=url,
            price_paise=price_paise,
            reasons_json=json.dumps(reasons),
            telegram_status="held",
            scheduled_for=scheduled,
            sent_at=None,
            created_at=now_dt,
        )
        session.add(alert)
        session.commit()
        session.refresh(alert)
        return alert

    sent = notifier.send_alert(payload)
    alert = RadarAlert(
        household_id=household_id,
        post_id=post_id,
        product_key=product_key,
        platform=platform,
        sku=sku,
        title=title,
        url=url,
        price_paise=price_paise,
        reasons_json=json.dumps(reasons),
        telegram_status="sent" if sent else "skipped",
        scheduled_for=None,
        sent_at=now_dt if sent else None,
        created_at=now_dt,
    )
    session.add(alert)
    session.commit()
    session.refresh(alert)
    return alert


def send_due_alerts(
    session: Session,
    now: datetime,
    notifier: Notifier,
) -> int:
    """Flush held quiet-hour Telegram alerts whose scheduled_for <= now."""
    now_utc = to_utc(now)
    held_alerts = session.exec(
        select(RadarAlert).where(RadarAlert.telegram_status == "held")
    ).all()

    sent_count = 0
    for alert in held_alerts:
        if alert.scheduled_for is not None and to_utc(alert.scheduled_for) > now_utc:
            continue
        try:
            reasons = json.loads(alert.reasons_json)
            if not isinstance(reasons, list):
                reasons = []
        except Exception:
            reasons = []

        payload = AlertPayload(
            title=alert.title,
            price_paise=alert.price_paise,
            reasons=[str(r) for r in reasons],
            url=alert.url,
            platform=alert.platform,
        )
        sent = notifier.send_alert(payload)
        alert.telegram_status = "sent" if sent else "skipped"
        if sent:
            alert.sent_at = now
            sent_count += 1
        session.add(alert)

    if held_alerts:
        session.commit()
    return sent_count
