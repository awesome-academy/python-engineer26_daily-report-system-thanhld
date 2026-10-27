"""Session database cho lệnh CLI."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import typer
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app import models as _models  # noqa: F401 (nạp đủ model trước khi SQLAlchemy nối quan hệ)
from app.core.config import get_settings


@asynccontextmanager
async def cli_session() -> AsyncIterator[AsyncSession]:
    # Engine riêng không giữ kết nối: mỗi lệnh CLI chạy trong event loop riêng rồi kết thúc.
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session
    finally:
        await engine.dispose()


def exit_with_validation_errors(exc: ValidationError, field: str = "giá trị") -> typer.Exit:
    """In lỗi validate theo từng trường, trả về Exit để caller `raise ... from exc`.

    `field` là tên in ra khi lỗi không gắn với trường nào (validate một giá trị qua TypeAdapter).
    """
    for error in exc.errors():
        name = error["loc"][0] if error["loc"] else field
        typer.secho(f"{name}: {error['msg']}", fg=typer.colors.RED, err=True)
    return typer.Exit(code=1)
