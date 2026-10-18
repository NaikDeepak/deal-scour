import sqlite3
from collections.abc import Generator
from functools import lru_cache
from pathlib import Path
from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlmodel import Session, create_engine

from app.core.config import get_settings


def _set_sqlite_pragma(dbapi_connection: Any, connection_record: Any) -> None:
    if isinstance(dbapi_connection, sqlite3.Connection):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()


def create_db_engine(db_path_or_url: Path | str | None = None) -> Engine:
    if db_path_or_url is None:
        settings = get_settings()
        settings.ensure_db_dir()
        url = settings.db_url
    elif isinstance(db_path_or_url, Path):
        url = f"sqlite:///{db_path_or_url.resolve()}"
    else:
        url = db_path_or_url

    eng = create_engine(
        url,
        connect_args={"check_same_thread": False},
    )
    event.listen(eng, "connect", _set_sqlite_pragma)
    return eng


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    # Created on first use, not at import: importing the app must not touch the filesystem.
    return create_db_engine()


def get_session() -> Generator[Session, None, None]:
    with Session(get_engine()) as session:
        yield session


def current_household_id() -> int: return 1  # HOOK: replaced by auth (ADR-013)
