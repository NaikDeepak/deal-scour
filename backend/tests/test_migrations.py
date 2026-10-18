from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlmodel import Session, SQLModel

import app.domain.models  # noqa: F401
from app.core.db import create_db_engine


def test_migrations_create_expected_schema_and_household(tmp_path: Path) -> None:
    db_file = tmp_path / "migration_test.db"
    db_url = f"sqlite:///{db_file.resolve()}"

    alembic_cfg = Config(str(Path(__file__).parent.parent / "alembic.ini"))
    alembic_cfg.set_main_option("sqlalchemy.url", db_url)
    alembic_cfg.set_main_option("script_location", str(Path(__file__).parent.parent / "migrations"))

    command.upgrade(alembic_cfg, "head")

    engine = create_db_engine(db_file)
    inspector = sa.inspect(engine)
    table_names = set(inspector.get_table_names())
    # Exclude alembic_version
    user_tables = table_names - {"alembic_version"}
    expected_tables = {"household", "shopping_list", "need", "offer"}
    assert user_tables == expected_tables

    # Compare columns between SQLModel.metadata and database schema
    for table_name in expected_tables:
        model_cols = {col.name for col in SQLModel.metadata.tables[table_name].columns}
        db_cols = {col["name"] for col in inspector.get_columns(table_name)}
        assert model_cols == db_cols, f"Column mismatch in table {table_name}: {model_cols} != {db_cols}"

    # Verify household id=1 is inserted
    with Session(engine) as session:
        household_cls = SQLModel.metadata.tables["household"]
        stmt = sa.select(household_cls).where(household_cls.c.id == 1)
        row = session.exec(stmt).first()
        assert row is not None
        assert row.name == "Home"
        assert row.pincode == "411018"


def test_sqlite_pragmas(tmp_path: Path) -> None:
    db_file = tmp_path / "pragma_test.db"
    engine = create_db_engine(db_file)

    with engine.connect() as conn:
        fk_result = conn.execute(sa.text("PRAGMA foreign_keys")).scalar()
        assert fk_result == 1

        jm_result = conn.execute(sa.text("PRAGMA journal_mode")).scalar()
        assert str(jm_result).lower() == "wal"
