import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core.security import verify_password
from app.modules.users.models import User, UserRole
from app.modules.users.repository import UserRepository
from tests.helpers import invoke


@pytest.fixture
async def admin_email(engine: AsyncEngine) -> AsyncIterator[str]:
    """CLI commit thật vào DB test, nên xóa user đã tạo sau mỗi test."""
    email = f"admin-{uuid.uuid4().hex[:8]}@example.com"
    yield email
    async with engine.begin() as connection:
        await connection.execute(delete(User).where(User.email == email))


async def test_create_admin_creates_admin_who_can_log_in(
    engine: AsyncEngine, admin_email: str
) -> None:
    result = await invoke(
        "create-admin", "--email", admin_email, "--full-name", "Quản trị viên",
        "--password", "Matkhau@123",
    )  # fmt: skip

    assert result.exit_code == 0, result.output
    assert "Đã tạo admin #" in result.output
    async with AsyncSession(engine) as session:
        user = await UserRepository(session).get_by_email(admin_email)
    assert user is not None
    assert user.role == UserRole.ADMIN
    assert user.password_hash is not None
    assert await verify_password("Matkhau@123", user.password_hash)


async def test_create_admin_rejects_duplicate_email(admin_email: str) -> None:
    args = ("create-admin", "--email", admin_email, "--full-name", "A", "--password", "Matkhau@123")
    await invoke(*args)

    result = await invoke(*args)

    assert result.exit_code == 1
    assert "Email đã được dùng" in result.output


@pytest.mark.parametrize(
    ("email", "password", "field"),
    [
        ("khong-phai-email", "Matkhau@123", "email"),
        ("ok@example.com", "ngan", "password"),
        ("ok@example.com", "matkhaudai123", "password"),
    ],
)
async def test_create_admin_validates_input(email: str, password: str, field: str) -> None:
    result = await invoke(
        "create-admin", "--email", email, "--full-name", "A", "--password", password
    )

    assert result.exit_code == 1
    assert f"{field}:" in result.output
