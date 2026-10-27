import asyncio

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession


async def _unaccent_function_exists(engine: AsyncEngine) -> bool:
    async with engine.connect() as connection:
        found = await connection.scalar(
            text("SELECT 1 FROM pg_proc WHERE proname = 'immutable_unaccent'")
        )
    return found is not None


async def test_migrations_can_downgrade_and_upgrade_again(
    engine: AsyncEngine, alembic_config: Config
) -> None:
    await asyncio.to_thread(command.downgrade, alembic_config, "base")
    assert not await _unaccent_function_exists(engine)

    await asyncio.to_thread(command.upgrade, alembic_config, "head")
    assert await _unaccent_function_exists(engine)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Nguyễn Văn Đức", "nguyen van duc"),
        ("TRẦN THỊ HỒNG NHUNG", "tran thi hong nhung"),
        ("Lê Ánh", "le anh"),
    ],
)
async def test_immutable_unaccent_strips_vietnamese_marks(
    db_session: AsyncSession, name: str, expected: str
) -> None:
    result = await db_session.scalar(
        text("SELECT immutable_unaccent(lower(:name))"), {"name": name}
    )

    assert result == expected
