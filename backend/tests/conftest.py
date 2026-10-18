from collections.abc import Generator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlmodel import Session

from app.api.v1.lists import router as lists_router
from app.api.v1.offers import router as offers_router
from app.core.db import create_db_engine, get_session


@pytest.fixture
def test_db_path(tmp_path: Path) -> Path:
    return tmp_path / "test.db"


@pytest.fixture
def engine(test_db_path: Path) -> Generator[Engine, None, None]:
    db_url = f"sqlite:///{test_db_path.resolve()}"
    alembic_cfg = Config(str(Path(__file__).parent.parent / "alembic.ini"))
    alembic_cfg.set_main_option("sqlalchemy.url", db_url)
    alembic_cfg.set_main_option("script_location", str(Path(__file__).parent.parent / "migrations"))
    command.upgrade(alembic_cfg, "head")

    eng = create_db_engine(test_db_path)
    try:
        yield eng
    finally:
        eng.dispose()


@pytest.fixture
def session(engine: Engine) -> Generator[Session, None, None]:
    with Session(engine) as s:
        yield s


@pytest.fixture
def client(engine: Engine) -> Generator[TestClient, None, None]:
    app = FastAPI()
    app.include_router(lists_router, prefix="/api/v1")
    app.include_router(offers_router, prefix="/api/v1")

    def override_get_session() -> Generator[Session, None, None]:
        with Session(engine) as s:
            yield s

    app.dependency_overrides[get_session] = override_get_session
    with TestClient(app) as c:
        yield c
