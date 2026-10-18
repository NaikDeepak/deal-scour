import os
from dataclasses import dataclass
from pathlib import Path


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
        dev_login = os.environ.get("DEALSCOUR_DEV_LOGIN") == "1"
        secret_key = os.environ.get("DEALSCOUR_SECRET_KEY", "")
        if not secret_key and not dev_login:
            raise RuntimeError("DEALSCOUR_SECRET_KEY is required in non-dev mode")
        if not secret_key and dev_login:
            secret_key = "dev-insecure-secret-key"

        owner_email = os.environ.get("DEALSCOUR_OWNER_EMAIL", "").strip().lower()
        base_url = os.environ.get("DEALSCOUR_BASE_URL", "")
        smtp_host = os.environ.get("SMTP_HOST", "")
        smtp_port_raw = os.environ.get("SMTP_PORT", "587")
        try:
            smtp_port = int(smtp_port_raw)
        except ValueError:
            smtp_port = 587
        smtp_user = os.environ.get("SMTP_USER", "")
        smtp_password = os.environ.get("SMTP_PASSWORD", "")
        smtp_from = os.environ.get("SMTP_FROM", "")

        static = os.environ.get("DEALSCOUR_STATIC_DIR")
        return cls(
            db_path=Path(os.environ.get("DEALSCOUR_DB_PATH", "./data/dealscour.db")),
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
        )


def get_settings() -> Settings:
    return Settings.from_env()
