from datetime import UTC, datetime
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
    expected_tables = {
        "household",
        "shopping_list",
        "need",
        "offer",
        "plan_run",
        "basket",
        "basket_line",
        "price_observation",
        "app_user",
        "household_member",
        "login_code",
        "auth_session",
        "invite",
        "custom_listing",
    }
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


def test_migration_0002_upgrade_preserves_data(tmp_path: Path) -> None:
    db_file = tmp_path / "upgrade_test.db"
    db_url = f"sqlite:///{db_file.resolve()}"

    alembic_cfg = Config(str(Path(__file__).parent.parent / "alembic.ini"))
    alembic_cfg.set_main_option("sqlalchemy.url", db_url)
    alembic_cfg.set_main_option("script_location", str(Path(__file__).parent.parent / "migrations"))

    # 1. Upgrade to 0001_initial
    command.upgrade(alembic_cfg, "0001_initial")

    engine = create_db_engine(db_file)
    with Session(engine) as session:
        shopping_list_table = SQLModel.metadata.tables["shopping_list"]
        session.exec(
            sa.insert(shopping_list_table).values(
                id=1,
                household_id=1,
                name="Test List Pre-Upgrade",
                kind="monthly",
                archived=False,
                created_at=datetime.now(UTC),
            )
        )
        session.commit()
    engine.dispose()

    # 2. Upgrade to head (0002_baskets)
    command.upgrade(alembic_cfg, "head")

    # 3. Verify list still exists without data loss
    engine2 = create_db_engine(db_file)
    with Session(engine2) as session:
        shopping_list_table = SQLModel.metadata.tables["shopping_list"]
        row = session.exec(sa.select(shopping_list_table).where(shopping_list_table.c.id == 1)).first()
        assert row is not None
        assert row.name == "Test List Pre-Upgrade"
        assert row.kind == "monthly"
    engine2.dispose()


def test_migration_0003_upgrade_preserves_data(tmp_path: Path) -> None:
    db_file = tmp_path / "upgrade_0003_test.db"
    db_url = f"sqlite:///{db_file.resolve()}"

    alembic_cfg = Config(str(Path(__file__).parent.parent / "alembic.ini"))
    alembic_cfg.set_main_option("sqlalchemy.url", db_url)
    alembic_cfg.set_main_option("script_location", str(Path(__file__).parent.parent / "migrations"))

    # 1. Upgrade to 0002_baskets
    command.upgrade(alembic_cfg, "0002_baskets")

    engine = create_db_engine(db_file)
    with Session(engine) as session:
        basket_table = SQLModel.metadata.tables["basket"]
        plan_run_table = SQLModel.metadata.tables["plan_run"]
        session.exec(
            sa.insert(plan_run_table).values(
                id=1,
                household_id=1,
                request_json="{}",
                response_json="{}",
                created_at=datetime.now(UTC),
            )
        )
        session.exec(
            sa.insert(basket_table).values(
                id=1,
                household_id=1,
                plan_run_id=1,
                platform="amazon",
                status="ready",
                planned_net_paise=50000,
                created_at=datetime.now(UTC),
            )
        )
        session.commit()
    engine.dispose()

    # 2. Upgrade to head (0003_price_observation)
    command.upgrade(alembic_cfg, "head")

    # 3. Verify basket still intact and price_observation table exists
    engine2 = create_db_engine(db_file)
    inspector = sa.inspect(engine2)
    assert "price_observation" in inspector.get_table_names()

    with Session(engine2) as session:
        basket_table = SQLModel.metadata.tables["basket"]
        row = session.exec(sa.select(basket_table).where(basket_table.c.id == 1)).first()
        assert row is not None
        assert row.platform == "amazon"
        assert row.planned_net_paise == 50000
    engine2.dispose()


def test_migration_0004_upgrade_preserves_data(tmp_path: Path) -> None:
    db_file = tmp_path / "upgrade_0004_test.db"
    db_url = f"sqlite:///{db_file.resolve()}"

    alembic_cfg = Config(str(Path(__file__).parent.parent / "alembic.ini"))
    alembic_cfg.set_main_option("sqlalchemy.url", db_url)
    alembic_cfg.set_main_option("script_location", str(Path(__file__).parent.parent / "migrations"))

    # 1. Upgrade to 0003_price_observation
    command.upgrade(alembic_cfg, "0003_price_observation")

    engine = create_db_engine(db_file)
    with Session(engine) as session:
        shopping_list_table = SQLModel.metadata.tables["shopping_list"]
        session.exec(
            sa.insert(shopping_list_table).values(
                id=1,
                household_id=1,
                name="Existing List",
                kind="quick",
                archived=False,
                created_at=datetime.now(UTC),
            )
        )
        session.commit()
    engine.dispose()

    # 2. Upgrade to head (0004_auth)
    command.upgrade(alembic_cfg, "head")

    # 3. Verify existing household 1 data intact and auth tables exist
    engine2 = create_db_engine(db_file)
    inspector = sa.inspect(engine2)
    auth_tables = {"app_user", "household_member", "login_code", "auth_session", "invite"}
    assert auth_tables.issubset(set(inspector.get_table_names()))

    with Session(engine2) as session:
        shopping_list_table = SQLModel.metadata.tables["shopping_list"]
        row = session.exec(sa.select(shopping_list_table).where(shopping_list_table.c.id == 1)).first()
        assert row is not None
        assert row.name == "Existing List"
        assert row.household_id == 1
    engine2.dispose()


def test_migration_0005_upgrade_preserves_data(tmp_path: Path) -> None:
    db_file = tmp_path / "upgrade_0005_test.db"
    db_url = f"sqlite:///{db_file.resolve()}"

    alembic_cfg = Config(str(Path(__file__).parent.parent / "alembic.ini"))
    alembic_cfg.set_main_option("sqlalchemy.url", db_url)
    alembic_cfg.set_main_option("script_location", str(Path(__file__).parent.parent / "migrations"))

    # 1. Upgrade to 0004_auth
    command.upgrade(alembic_cfg, "0004_auth")

    engine = create_db_engine(db_file)
    with Session(engine) as session:
        shopping_list_table = SQLModel.metadata.tables["shopping_list"]
        session.exec(
            sa.insert(shopping_list_table).values(
                id=1,
                household_id=1,
                name="Existing List Pre-0005",
                kind="monthly",
                archived=False,
                created_at=datetime.now(UTC),
            )
        )
        session.commit()
    engine.dispose()

    # 2. Upgrade to head (0005_custom_listing)
    command.upgrade(alembic_cfg, "head")

    # 3. Verify existing household 1 data intact and custom_listing table exists
    engine2 = create_db_engine(db_file)
    inspector = sa.inspect(engine2)
    assert "custom_listing" in inspector.get_table_names()

    with Session(engine2) as session:
        shopping_list_table = SQLModel.metadata.tables["shopping_list"]
        row = session.exec(sa.select(shopping_list_table).where(shopping_list_table.c.id == 1)).first()
        assert row is not None
        assert row.name == "Existing List Pre-0005"
        assert row.household_id == 1
    engine2.dispose()


def test_sqlite_pragmas(tmp_path: Path) -> None:
    db_file = tmp_path / "pragma_test.db"
    engine = create_db_engine(db_file)

    with engine.connect() as conn:
        fk_result = conn.execute(sa.text("PRAGMA foreign_keys")).scalar()
        assert fk_result == 1

        jm_result = conn.execute(sa.text("PRAGMA journal_mode")).scalar()
        assert str(jm_result).lower() == "wal"
