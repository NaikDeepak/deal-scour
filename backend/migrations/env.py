from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, event, pool
from sqlmodel import SQLModel

import app.domain.models  # noqa: F401
from app.core.config import db_path_from_env
from app.core.db import _set_sqlite_pragma

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = SQLModel.metadata


def get_url() -> str:
    url = config.get_main_option("sqlalchemy.url")
    if not url:
        # Migrations only need the DB path, not the signing secret (Settings.from_env validates that).
        db_path = db_path_from_env()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        url = f"sqlite:///{db_path.resolve()}"
    return url


def run_migrations_offline() -> None:
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = get_url()

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    event.listen(connectable, "connect", _set_sqlite_pragma)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
