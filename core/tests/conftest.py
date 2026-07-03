from collections.abc import AsyncGenerator

import psycopg
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ember import models  # noqa: F401  (registers all tables on Base.metadata)
from ember.config import database_url, env
from ember.db import Base, get_db
from ember.main import app

TEST_DB_NAME = f"{env['DATABASE_NAME']}_test"


async def _ensure_database_exists(name: str) -> None:
    conn = await psycopg.AsyncConnection.connect(
        host=env["DATABASE_HOST"],
        port=env["DATABASE_PORT"],
        user=env["DATABASE_USER"],
        password=env["DATABASE_PASSWORD"],
        dbname="postgres",
        autocommit=True,
    )
    try:
        async with conn.cursor() as cur:
            await cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,))
            if not await cur.fetchone():
                await cur.execute(f'CREATE DATABASE "{name}"')
    finally:
        await conn.close()


@pytest.fixture(scope="session")
async def engine() -> AsyncGenerator[AsyncEngine, None]:
    await _ensure_database_exists(TEST_DB_NAME)
    test_engine = create_async_engine(database_url(database=TEST_DB_NAME))
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield test_engine
    await test_engine.dispose()


@pytest.fixture
async def db_session(engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    async with engine.connect() as connection:
        await connection.begin()
        session_factory = async_sessionmaker(
            bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
        )
        session = session_factory()
        try:
            yield session
        finally:
            await session.close()
            await connection.rollback()


@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        # Mirrors ember.db.get_db's commit/rollback-per-request semantics exactly,
        # so that one request's success is not wiped out by a later request's
        # failure sharing this same test transaction (see db_session above).
        try:
            yield db_session
            await db_session.commit()
        except Exception:
            await db_session.rollback()
            raise

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    # https, not http: the refresh-token cookie is Secure (docs/authentication.md
    # §4.4), and httpx's cookie jar correctly refuses to resend a Secure cookie
    # over a plain http:// origin — matching real browser behavior.
    async with AsyncClient(transport=transport, base_url="https://test") as ac:
        yield ac
    app.dependency_overrides.clear()
