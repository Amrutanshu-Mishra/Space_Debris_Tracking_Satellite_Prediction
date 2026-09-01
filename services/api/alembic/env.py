"""Alembic environment for the optional Postgres backend.

Resolves the URL from ``$DATABASE_URL`` first, then ``sqlalchemy.url`` in
alembic.ini. Runs online migrations through an async engine; offline mode
emits SQL against the same URL.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from prahari_api.config import get_settings
from prahari_api.db.tables import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

_settings_url = get_settings().database_url
if _settings_url:
    config.set_main_option("sqlalchemy.url", _settings_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        future=True,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(_do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
