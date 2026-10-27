"""Fixture dùng chung.

Test chạy trên PostgreSQL thật, database riêng (TEST_DATABASE_URL), Redis dùng DB số 15.
Mỗi test chạy trong một transaction và rollback khi kết thúc nên dữ liệu không lẫn nhau.

Engine và client Redis của app được tạo lúc import app.main, nên biến môi trường phải được
đặt trước. Vì vậy app chỉ được import bên trong fixture `app`, không import ở đầu file.
"""

import asyncio
import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import Settings

_settings = Settings()
TEST_DATABASE_URL = _settings.test_database_url
TEST_REDIS_URL = _settings.redis_url.rsplit("/", 1)[0] + "/15"
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["REDIS_URL"] = TEST_REDIS_URL
os.environ["ENVIRONMENT"] = "test"

ROOT_DIR = Path(__file__).resolve().parents[1]


def make_alembic_config() -> Config:
    config = Config(str(ROOT_DIR / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)
    return config


async def _create_database_if_missing(url: str) -> None:
    target = make_url(url)
    admin_engine = create_async_engine(
        target.set(database="postgres"), isolation_level="AUTOCOMMIT", poolclass=NullPool
    )
    try:
        async with admin_engine.connect() as connection:
            exists = await connection.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": target.database},
            )
            if not exists:
                await connection.execute(text(f'CREATE DATABASE "{target.database}"'))
    finally:
        await admin_engine.dispose()


@pytest.fixture
def alembic_config() -> Config:
    return make_alembic_config()


@pytest.fixture(scope="session")
async def engine() -> AsyncIterator[AsyncEngine]:
    await _create_database_if_missing(TEST_DATABASE_URL)
    # env.py của Alembic tự chạy asyncio.run(), nên phải chạy ở thread khác event loop của test.
    await asyncio.to_thread(command.upgrade, make_alembic_config(), "head")
    test_engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    yield test_engine
    await test_engine.dispose()


@pytest.fixture
async def db_session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    async with engine.connect() as connection:
        transaction = await connection.begin()
        session = AsyncSession(
            bind=connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        try:
            yield session
        finally:
            await session.close()
            await transaction.rollback()


@pytest.fixture
def app() -> Iterator[FastAPI]:
    from app.main import app as fastapi_app  # noqa: PLC0415 (xem docstring của module)

    yield fastapi_app
    fastapi_app.dependency_overrides.clear()


@pytest.fixture
async def client(app: FastAPI, db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    from app.core.database import get_db_session  # noqa: PLC0415 (xem docstring của module)

    app.dependency_overrides[get_db_session] = lambda: db_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http
