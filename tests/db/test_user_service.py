import asyncio
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.modules.departments.exceptions import DepartmentNotEmptyError, DepartmentNotFoundError
from app.modules.departments.models import Department
from app.modules.departments.repository import DepartmentRepository
from app.modules.departments.service import DepartmentService
from app.modules.users.exceptions import EmailAlreadyExistsError
from app.modules.users.models import User, UserRole
from app.modules.users.repository import UserRepository
from app.modules.users.schemas import AdminUserCreate, AdminUserUpdate, UserCreate
from app.modules.users.service import UserService
from tests.factories import DEFAULT_PASSWORD, create_user


async def no_user_with_email(_: UserRepository, __: str) -> User | None:
    return None


def new_user(email: str) -> UserCreate:
    return UserCreate(email=email, full_name="Nguyễn Văn An", password=DEFAULT_PASSWORD)


async def test_create_user_rejects_email_differing_only_in_case(db_session: AsyncSession) -> None:
    await create_user(db_session, email="an@example.com")

    with pytest.raises(EmailAlreadyExistsError):
        await UserService(db_session).create_user(new_user("An@Example.com"))


async def test_create_user_maps_concurrent_duplicate_to_email_already_exists(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    await create_user(db_session, email="an@example.com")

    # Giả lập lệnh tạo song song: lúc kiểm tra, user kia chưa được insert.
    monkeypatch.setattr(UserRepository, "get_by_email", no_user_with_email)

    with pytest.raises(EmailAlreadyExistsError):
        await UserService(db_session).create_user(new_user("an@example.com"))


async def test_update_by_admin_maps_concurrent_duplicate_email_to_email_already_exists(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin = await create_user(db_session, role=UserRole.ADMIN)
    await create_user(db_session, email="binh@example.com")
    user = await create_user(db_session, email="an@example.com")
    # Giả lập request khác đổi sang cùng email: lúc kiểm tra, email đó chưa có ai dùng.
    monkeypatch.setattr(UserRepository, "get_by_email", no_user_with_email)

    with pytest.raises(EmailAlreadyExistsError):
        await UserService(db_session).update_by_admin(
            admin, user.id, AdminUserUpdate(email="binh@example.com")
        )


AssignDepartment = Callable[[AsyncSession, User, int], Coroutine[Any, Any, User]]


async def assign_by_update(session: AsyncSession, admin: User, department_id: int) -> User:
    target = User(email="an@example.com", full_name="Nguyễn Văn An")
    session.add(target)
    await session.flush()
    target_id = target.id
    await session.commit()
    return await UserService(session).update_by_admin(
        admin, target_id, AdminUserUpdate(department_id=department_id)
    )


async def assign_by_create(session: AsyncSession, admin: User, department_id: int) -> User:
    return await UserService(session).create_by_admin(
        AdminUserCreate(
            email="an@example.com", full_name="Nguyễn Văn An", department_id=department_id
        )
    )


@pytest.mark.parametrize("assign", [assign_by_update, assign_by_create], ids=["update", "create"])
async def test_assign_department_waits_for_concurrent_delete_and_returns_not_found(
    engine: AsyncEngine, assign: AssignDepartment
) -> None:
    # Hai session thật, commit thật: khóa dòng chỉ có tác dụng giữa các transaction khác nhau.
    async with AsyncSession(engine, expire_on_commit=False) as setup:
        department = Department(code="RACE", name="Phòng")
        admin = User(email="admin@example.com", full_name="Quản trị viên", role=UserRole.ADMIN)
        setup.add_all([department, admin])
        await setup.commit()
    try:
        async with AsyncSession(engine) as deleting, AsyncSession(engine) as assigning:
            # Lệnh xóa bộ phận đang giữ khóa dòng (đã đếm 0 thành viên), chưa commit.
            locked = await DepartmentRepository(deleting).get_by_id_for_update(department.id)
            assert locked is not None
            locked.deleted_at = datetime.now(UTC)
            await deleting.flush()

            assignment = asyncio.create_task(assign(assigning, admin, department.id))
            await asyncio.sleep(0.3)
            await deleting.commit()

            # Không chờ khóa thì lệnh gán đọc bộ phận chưa xóa, user vào bộ phận vừa bị xóa.
            with pytest.raises(DepartmentNotFoundError):
                await assignment
    finally:
        async with engine.begin() as connection:
            await connection.execute(
                delete(User).where(User.email.in_(["an@example.com", "admin@example.com"]))
            )
            await connection.execute(delete(Department).where(Department.id == department.id))


async def test_delete_department_waits_for_assignment_holding_share_lock(
    engine: AsyncEngine,
) -> None:
    async with AsyncSession(engine, expire_on_commit=False) as setup:
        department = Department(code="RACE", name="Phòng")
        user = User(email="an@example.com", full_name="Nguyễn Văn An")
        setup.add_all([department, user])
        await setup.commit()
    try:
        async with AsyncSession(engine) as assigning, AsyncSession(engine) as deleting:
            # Lệnh gán đã khóa FOR SHARE và ghi department_id như update_by_admin, chưa commit.
            locked = await DepartmentRepository(assigning).get_by_id_for_share(department.id)
            assert locked is not None
            target = await assigning.get(User, user.id)
            assert target is not None
            target.department_id = department.id
            await assigning.flush()

            deletion = asyncio.create_task(
                DepartmentService(deleting).delete_department(department.id)
            )
            await asyncio.sleep(0.3)
            await assigning.commit()

            # Lệnh xóa chờ khóa, đếm thành viên sau khi lệnh gán commit nên thấy user vừa gán.
            with pytest.raises(DepartmentNotEmptyError):
                await deletion
    finally:
        async with engine.begin() as connection:
            await connection.execute(delete(User).where(User.id == user.id))
            await connection.execute(delete(Department).where(Department.id == department.id))
