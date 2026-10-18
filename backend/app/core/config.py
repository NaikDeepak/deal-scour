import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    db_path: Path

    @property
    def db_url(self) -> str:
        return f"sqlite:///{self.db_path.resolve()}"

    def ensure_db_dir(self) -> None:
        if str(self.db_path) != ":memory:":
            self.db_path.parent.mkdir(parents=True, exist_ok=True)

    @classmethod
    def from_env(cls) -> "Settings":
        raw_path = os.environ.get("DEALSCOUR_DB_PATH", "./data/dealscour.db")
        path = Path(raw_path)
        settings = cls(db_path=path)
        settings.ensure_db_dir()
        return settings


def get_settings() -> Settings:
    return Settings.from_env()
