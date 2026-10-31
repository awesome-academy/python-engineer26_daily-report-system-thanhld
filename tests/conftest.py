"""Fixture dùng chung.

Test chạy trên PostgreSQL thật, database riêng (TEST_DATABASE_URL), Redis dùng DB riêng
(TEST_REDIS_URL).
Mỗi test chạy trong một transaction và rollback khi kết thúc nên dữ liệu không lẫn nhau.

Engine và client Redis của app được tạo lúc import, nên biến môi trường phải được đặt trước.
Vì vậy app.models chỉ được import sau phần đặt biến môi trường, còn app.main chỉ được import
bên trong fixture `app`.
"""

import asyncio
import os
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import Settings

_settings = Settings()
TEST_DATABASE_URL = _settings.test_database_url
TEST_REDIS_URL = _settings.test_redis_url
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["REDIS_URL"] = TEST_REDIS_URL
os.environ["ENVIRONMENT"] = "test"


def _redis_target(url: str) -> tuple[str | None, int | None, int]:
    """Host, cổng, số DB của URL Redis (không ghi số DB thì là DB 0)."""
    parts = urlsplit(url)
    return parts.hostname, parts.port, int(parts.path.lstrip("/") or 0)


# Chặn nhầm database: test xóa và ghi dữ liệu, chỉ được chạy trên database tên kết thúc bằng _test.
if not str(make_url(TEST_DATABASE_URL).database).endswith("_test"):
    msg = f"TEST_DATABASE_URL phải trỏ tới database *_test, đang là {TEST_DATABASE_URL!r}"
    raise RuntimeError(msg)
# Fixture `redis` xóa sạch DB Redis của test, nên DB này không được trùng DB dev.
if _redis_target(TEST_REDIS_URL) == _redis_target(_settings.redis_url):
    msg = f"TEST_REDIS_URL phải dùng DB Redis khác REDIS_URL, đang là {TEST_REDIS_URL!r}"
    raise RuntimeError(msg)

# Chỉ import sau khi đặt biến môi trường: app.models kéo theo app.core.database, nơi engine được
# tạo từ DATABASE_URL. Import sớm hơn thì engine trỏ vào database dev.
from app import models as _models  # noqa: E402, F401
from app.core.database import Base  # noqa: E402
from app.core.database import engine as app_engine  # noqa: E402
from app.core.redis import redis_client  # noqa: E402

if app_engine.url.database != make_url(TEST_DATABASE_URL).database:
    msg = f"Engine của app đang trỏ tới {app_engine.url.database!r}, không phải database test"
    raise RuntimeError(msg)

if redis_client.connection_pool.connection_kwargs.get("db") != _redis_target(TEST_REDIS_URL)[2]:
    msg = f"Client Redis của app không trỏ tới {TEST_REDIS_URL!r}"
    raise RuntimeError(msg)

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
async def clean_after(engine: AsyncEngine) -> AsyncIterator[None]:
    """Test commit thật vào DB test (lệnh CLI, nhiều kết nối song song): xóa sạch sau test."""
    yield
    tables = ", ".join(table.name for table in Base.metadata.sorted_tables)
    async with engine.begin() as connection:
        await connection.execute(text(f"TRUNCATE TABLE {tables} RESTART IDENTITY CASCADE"))


@pytest.fixture
async def redis() -> Redis:
    # Blacklist token và bộ đếm đăng nhập sai không được lẫn giữa các test.
    await redis_client.flushdb()
    return redis_client


@pytest.fixture
def app() -> Iterator[FastAPI]:
    from app.main import app as fastapi_app  # noqa: PLC0415 (xem docstring của module)

    yield fastapi_app
    fastapi_app.dependency_overrides.clear()


@asynccontextmanager
async def _http_client(app: FastAPI, db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    from app.core.database import get_db_session  # noqa: PLC0415 (xem docstring của module)

    app.dependency_overrides[get_db_session] = lambda: db_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http


@pytest.fixture
async def client(
    app: FastAPI, db_session: AsyncSession, redis: Redis
) -> AsyncIterator[AsyncClient]:
    async with _http_client(app, db_session) as http:
        yield http


@pytest.fixture
def probe_app() -> FastAPI:
    """App riêng để test gắn route thăm dò, thử dependency khi chưa có endpoint thật dùng nó.

    Không gắn vào app dùng chung: route thêm vào sẽ còn lại cho mọi test sau.
    """
    from app.main import create_app  # noqa: PLC0415 (xem docstring của module)

    return create_app()


@pytest.fixture
async def probe_client(
    probe_app: FastAPI, db_session: AsyncSession, redis: Redis
) -> AsyncIterator[AsyncClient]:
    async with _http_client(probe_app, db_session) as http:
        yield http
