import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


@dataclass(frozen=True)
class Settings:
    db_path: Path
    static_dir: Path | None = None  # built web app to serve (set in the Docker image)
    secret_key: str = ""
    owner_email: str = ""
    dev_login: bool = False
    base_url: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    fetchers_enabled: bool = False
    fetch_interval_hours: int = 6

    @property
    def db_url(self) -> str:
        return f"sqlite:///{self.db_path.resolve()}"

    @property
    def cookie_secure(self) -> bool:
        return self.base_url.lower().startswith("https")

    def ensure_db_dir(self) -> None:
        if str(self.db_path) != ":memory:":
            self.db_path.parent.mkdir(parents=True, exist_ok=True)

    @classmethod
    def from_env(cls) -> "Settings":
        secret_key = os.environ.get("DEALSCOUR_SECRET_KEY", "")
        if not secret_key:
            raise RuntimeError("DEALSCOUR_SECRET_KEY is required in all modes")
        if len(secret_key) < 32:
            raise RuntimeError("DEALSCOUR_SECRET_KEY must be at least 32 characters")

        dev_login = os.environ.get("DEALSCOUR_DEV_LOGIN") == "1"
        base_url = os.environ.get("DEALSCOUR_BASE_URL", "http://localhost:8000")

        if dev_login:
            parsed = urlparse(base_url)
            host = (parsed.hostname or "").lower()
            if host not in ("localhost", "127.0.0.1", "::1"):
                raise RuntimeError(
                    "DEALSCOUR_DEV_LOGIN is only allowed when DEALSCOUR_BASE_URL host is "
                    f"localhost or 127.0.0.1, got: {host}"
                )

        owner_email = os.environ.get("DEALSCOUR_OWNER_EMAIL", "").strip().lower()
        smtp_host = os.environ.get("SMTP_HOST", "")
        smtp_port_raw = os.environ.get("SMTP_PORT", "587")
        try:
            smtp_port = int(smtp_port_raw)
        except ValueError:
            smtp_port = 587
        smtp_user = os.environ.get("SMTP_USER", "")
        smtp_password = os.environ.get("SMTP_PASSWORD", "")
        smtp_from = os.environ.get("SMTP_FROM", "")

        fetchers_enabled = os.environ.get("DEALSCOUR_FETCHERS") == "1"
        fetch_interval_raw = os.environ.get("DEALSCOUR_FETCH_INTERVAL_HOURS", "6")
        try:
            fetch_interval_hours = max(2, int(fetch_interval_raw))
        except ValueError:
            fetch_interval_hours = 6

        static = os.environ.get("DEALSCOUR_STATIC_DIR")
        return cls(
            db_path=db_path_from_env(),
            static_dir=Path(static) if static else None,
            secret_key=secret_key,
            owner_email=owner_email,
            dev_login=dev_login,
            base_url=base_url,
            smtp_host=smtp_host,
            smtp_port=smtp_port,
            smtp_user=smtp_user,
            smtp_password=smtp_password,
            smtp_from=smtp_from,
            fetchers_enabled=fetchers_enabled,
            fetch_interval_hours=fetch_interval_hours,
        )


def db_path_from_env() -> Path:
    """DB location only, no secret validation: migrations and backups never sign anything."""
    return Path(os.environ.get("DEALSCOUR_DB_PATH", "./data/dealscour.db"))


def get_settings() -> Settings:
    return Settings.from_env()
