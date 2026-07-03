import asyncio
from logging.config import fileConfig

from sqlalchemy import Connection

from alembic import context
from ember import models  # noqa: F401  (registers all tables on Base.metadata)
from ember.config import database_url
from ember.db import Base, engine

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Built from validated env vars (venvalid), never read from alembic.ini
# (docs/authentication.md: no secrets in config files).
config.set_main_option("sqlalchemy.url", database_url())

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Reuse the app's own async engine (ember.db.engine) instead of building
    a second one from the .ini file, so migrations and app runtime share one
    source of truth for the connection.
    """
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await engine.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
