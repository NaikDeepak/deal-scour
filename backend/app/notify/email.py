import logging
import smtplib
from email.message import EmailMessage
from typing import Protocol

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class EmailSender(Protocol):
    def send_login_code(self, email: str, code: str) -> None:
        ...


class SmtpSender:
    def __init__(
        self,
        host: str,
        port: int,
        user: str,
        password: str,
        from_addr: str,
    ) -> None:
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.from_addr = from_addr

    def send_login_code(self, email: str, code: str) -> None:
        msg = EmailMessage()
        msg["Subject"] = f"Your DealScour login code: {code}"
        msg["From"] = self.from_addr or "noreply@dealscour.local"
        msg["To"] = email
        msg.set_content(
            f"Hello,\n\nYour DealScour login code is: {code}\n\n"
            f"This code will expire in 10 minutes.\n"
            f"If you did not request this, you can ignore this email.\n"
        )

        if self.port == 465:
            server: smtplib.SMTP = smtplib.SMTP_SSL(self.host, self.port)
        else:
            server = smtplib.SMTP(self.host, self.port)
        try:
            if self.port != 465:
                server.starttls()
            if self.user and self.password:
                server.login(self.user, self.password)
            server.send_message(msg)
        finally:
            server.quit()


class LogSender:
    """Dev-only sender that prints the login code when DEALSCOUR_DEV_LOGIN=1."""

    def send_login_code(self, email: str, code: str) -> None:
        settings = get_settings()
        if settings.dev_login:
            logger.warning("[DEV LOGIN] Login code for %s is: %s", email, code)
        else:
            logger.info("Login code requested for %s (suppressed in non-dev mode)", email)


def get_email_sender() -> EmailSender:
    settings = get_settings()
    if settings.dev_login:
        logger.warning("*** WARNING: DEALSCOUR_DEV_LOGIN is ON! Never use this in production! ***")
        return LogSender()
    if settings.smtp_host:
        return SmtpSender(
            host=settings.smtp_host,
            port=settings.smtp_port,
            user=settings.smtp_user,
            password=settings.smtp_password,
            from_addr=settings.smtp_from,
        )
    return LogSender()
