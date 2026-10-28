import asyncio

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession


async def _schema_objects(engine: AsyncEngine) -> set[str]:
    async with engine.connect() as connection:
        rows = await connection.scalars(
            text(
                "SELECT proname FROM pg_proc WHERE proname = 'immutable_unaccent' "
                "UNION ALL SELECT tablename FROM pg_tables WHERE schemaname = 'public' "
                "AND tablename <> 'alembic_version' "
                "UNION ALL SELECT typname FROM pg_type WHERE typname = 'user_role'"
            )
        )
        return set(rows)


async def test_migrations_can_downgrade_and_upgrade_again(
    engine: AsyncEngine, alembic_config: Config
) -> None:
    await asyncio.to_thread(command.downgrade, alembic_config, "base")
    assert await _schema_objects(engine) == set()

    await asyncio.to_thread(command.upgrade, alembic_config, "head")
    assert await _schema_objects(engine) == {
        "immutable_unaccent",
        "user_role",
        "users",
        "departments",
        "department_managers",
        "daily_reports",
        "report_recipients",
        "refresh_tokens",
        "user_tokens",
        "email_logs",
    }


async def test_session_id_migration_keeps_existing_refresh_tokens(
    engine: AsyncEngine, alembic_config: Config
) -> None:
    await asyncio.to_thread(command.downgrade, alembic_config, "0003")
    try:
        async with engine.begin() as connection:
            user_id = await connection.scalar(
                text(
                    "INSERT INTO users (email, full_name) "
                    "VALUES ('migration@example.com', 'Test') RETURNING id"
                )
            )
            await connection.execute(
                text(
                    "INSERT INTO refresh_tokens (user_id, jti, expires_at) "
                    "VALUES (:user_id, 'jti-cu', now())"
                ),
                {"user_id": user_id},
            )

        await asyncio.to_thread(command.upgrade, alembic_config, "head")

        async with engine.connect() as connection:
            session_id = await connection.scalar(
                text("SELECT session_id FROM refresh_tokens WHERE jti = 'jti-cu'")
            )
        assert session_id == "jti-cu"
    finally:
        await asyncio.to_thread(command.upgrade, alembic_config, "head")
        async with engine.begin() as connection:
            await connection.execute(
                text("DELETE FROM users WHERE email = 'migration@example.com'")
            )


async def test_models_match_migrations(engine: AsyncEngine, alembic_config: Config) -> None:
    """Giống `alembic check`: model đổi mà quên tạo migration thì test này fail."""
    await asyncio.to_thread(command.check, alembic_config)


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
