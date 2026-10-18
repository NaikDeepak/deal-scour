import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    db_path: Path
    static_dir: Path | None = None  # built web app to serve (set in the Docker image)

    @property
    def db_url(self) -> str:
        return f"sqlite:///{self.db_path.resolve()}"

    def ensure_db_dir(self) -> None:
        if str(self.db_path) != ":memory:":
            self.db_path.parent.mkdir(parents=True, exist_ok=True)

    @classmethod
    def from_env(cls) -> "Settings":
        static = os.environ.get("DEALSCOUR_STATIC_DIR")
        return cls(
            db_path=Path(os.environ.get("DEALSCOUR_DB_PATH", "./data/dealscour.db")),
            static_dir=Path(static) if static else None,
        )


def get_settings() -> Settings:
    return Settings.from_env()
