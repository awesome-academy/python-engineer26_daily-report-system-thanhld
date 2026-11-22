import asyncio
from collections.abc import Collection, Sequence
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core import messages
from app.modules.departments.models import Department
from app.modules.departments.repository import DepartmentRepository
from app.modules.users.exceptions import EmailAlreadyExistsError, ImportValidationError
from app.modules.users.models import User
from app.modules.users.repository import UserRepository
from app.modules.users.service import UserImportService
from tests.factories import create_user
from tests.helpers import LOCK_WAIT_SECONDS, user_import_file

# Đủ nhiều email để hai lệnh INSERT chạy cùng lúc chạm nhau giữa chừng.
SHARED_EMAILS = 200


async def no_taken_emails(_: UserRepository, __: Collection[str]) -> set[str]:
    return set()


async def no_enqueue(_: Sequence[User]) -> None:
    return None


async def test_import_maps_concurrent_duplicate_email_to_email_already_exists(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    await create_user(db_session, email="an@example.com")
    # Giả lập import (hay tạo user) chạy song song: lúc kiểm tra, user kia chưa được insert.
    monkeypatch.setattr(UserRepository, "taken_emails", no_taken_emails)

    with pytest.raises(EmailAlreadyExistsError):
        await UserImportService(db_session).import_users(
            user_import_file(["an@example.com", "Nguyễn Văn An"])
        )


async def test_import_waits_for_concurrent_department_delete_and_reports_missing_code(
    engine: AsyncEngine,
) -> None:
    async with AsyncSession(engine, expire_on_commit=False) as setup:
        department = Department(code="RACE", name="Phòng")
        setup.add(department)
        await setup.commit()
    email = "an@example.com"
    try:
        async with AsyncSession(engine) as deleting, AsyncSession(engine) as importing:
            # Lệnh xóa bộ phận đã khóa dòng và đánh dấu xóa, chưa commit.
            locked = await DepartmentRepository(deleting).get_by_id_for_update(department.id)
            assert locked is not None
            locked.deleted_at = datetime.now(UTC)
            await deleting.flush()

            data = user_import_file([email, "Nguyễn Văn An", None, None, "RACE"])
            importing_users = asyncio.create_task(UserImportService(importing).import_users(data))
            await asyncio.sleep(LOCK_WAIT_SECONDS)
            await deleting.commit()

            # Import khóa FOR SHARE nên chờ lệnh xóa commit rồi mới đọc: không còn thấy bộ phận.
            # Không khóa thì import đọc bản cũ, xếp user vào bộ phận vừa bị xóa.
            with pytest.raises(ImportValidationError) as exc_info:
                await importing_users

        assert exc_info.value.details == [
            {"row": 2, "field": "department_code", "message": messages.IMPORT_DEPARTMENT_NOT_FOUND}
        ]
    finally:
        async with engine.begin() as connection:
            await connection.execute(delete(User).where(User.email == email))
            await connection.execute(delete(Department).where(Department.id == department.id))


async def test_concurrent_imports_with_shared_emails_in_different_order_do_not_deadlock(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Hai file chung email nhưng xếp ngược nhau: chèn theo thứ tự dòng thì mỗi transaction giữ
    # một đầu của unique index rồi chờ đầu kia (deadlock, PostgreSQL hủy một bên, API trả 500).
    monkeypatch.setattr(UserImportService, "_enqueue_setup_emails", staticmethod(no_enqueue))
    emails = [f"race{index:03d}@example.com" for index in range(SHARED_EMAILS)]
    forward = user_import_file(*[[email, "Nguyễn Văn An"] for email in emails])
    backward = user_import_file(*[[email, "Nguyễn Văn An"] for email in reversed(emails)])
    try:
        async with AsyncSession(engine) as first, AsyncSession(engine) as second:
            results = await asyncio.gather(
                UserImportService(first).import_users(forward),
                UserImportService(second).import_users(backward),
                return_exceptions=True,
            )

        # Request chèn sau chờ request trước commit rồi vấp unique index: 409, không ai bị tạo
        # trùng.
        assert sorted(type(result).__name__ for result in results) == [
            "EmailAlreadyExistsError",
            "list",
        ]
    finally:
        async with engine.begin() as connection:
            await connection.execute(delete(User).where(User.email.in_(emails)))
