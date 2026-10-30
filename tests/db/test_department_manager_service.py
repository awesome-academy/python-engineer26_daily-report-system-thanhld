import asyncio
from collections.abc import Callable
from typing import Any

import pytest
from sqlalchemy import Executable, Insert, Result, Update, func, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core.constants import BIGINT_MAX
from app.core.exceptions import AppError
from app.modules.departments.exceptions import DepartmentNotFoundError, ManagerRoleRequiredError
from app.modules.departments.models import Department
from app.modules.departments.service import DepartmentService
from app.modules.users.exceptions import UserInactiveError, UserNotFoundError
from app.modules.users.models import User, UserRole
from tests.factories import create_department, create_user

# Đủ để lệnh gán chạy tới bước khóa dòng trước khi transaction kia commit.
LOCK_WAIT_SECONDS = 0.3


@pytest.mark.parametrize(
    ("case", "error"),
    [
        ("missing-department", DepartmentNotFoundError),
        ("missing-user", UserNotFoundError),
        ("wrong-role", ManagerRoleRequiredError),
        ("inactive", UserInactiveError),
    ],
)
async def test_assign_manager_releases_locks_before_raising(
    db_session: AsyncSession, case: str, error: type[AppError]
) -> None:
    # Bộ phận, user bị khóa FOR SHARE: lỗi phải kết thúc transaction ngay, không chờ đóng session.
    department = await create_department(db_session)
    user = await create_user(
        db_session,
        role=UserRole.USER if case == "wrong-role" else UserRole.MANAGER,
        is_active=case != "inactive",
    )
    department_id = BIGINT_MAX if case == "missing-department" else department.id
    user_id = BIGINT_MAX if case == "missing-user" else user.id

    with pytest.raises(error):
        await DepartmentService(db_session).assign_manager(department_id, user_id)

    assert not db_session.in_transaction()


# Thay đổi admin khác thực hiện song song, dựng theo (department_id, user_id).
Change = Callable[[int, int], Update]


async def _assign_while_other_transaction_commits(
    engine: AsyncEngine, change: Change
) -> AppError | None:
    """Gán manager trong lúc transaction khác đang giữ khóa dòng và commit `change` sau đó."""
    async with AsyncSession(engine) as setup:
        department_id = (await create_department(setup)).id
        user_id = (await create_user(setup, role=UserRole.MANAGER)).id
        await setup.commit()

    async with AsyncSession(engine) as other, AsyncSession(engine) as session:
        # Admin khác đã khóa dòng (FOR UPDATE) và sửa xong, chưa commit.
        await other.execute(
            select(Department).where(Department.id == department_id).with_for_update()
        )
        await other.execute(select(User).where(User.id == user_id).with_for_update())
        await other.execute(change(department_id, user_id))
        assign = asyncio.create_task(
            DepartmentService(session).assign_manager(department_id, user_id)
        )
        # Có khóa thì lệnh gán phải chờ; không có thì nó đọc bản cũ và gán luôn.
        await asyncio.sleep(LOCK_WAIT_SECONDS)
        await other.commit()
        try:
            await assign
        except AppError as error:
            return error
        return None


@pytest.mark.usefixtures("clean_after")
@pytest.mark.parametrize(
    ("change", "error"),
    [
        pytest.param(
            lambda department_id, _: (
                update(Department)
                .where(Department.id == department_id)
                .values(deleted_at=func.now())
            ),
            DepartmentNotFoundError,
            id="department-deleted",
        ),
        pytest.param(
            lambda _, user_id: update(User).where(User.id == user_id).values(role=UserRole.USER),
            ManagerRoleRequiredError,
            id="role-changed",
        ),
        pytest.param(
            lambda _, user_id: update(User).where(User.id == user_id).values(is_active=False),
            UserInactiveError,
            id="user-locked",
        ),
    ],
)
async def test_assign_manager_waits_for_concurrent_change(
    engine: AsyncEngine, change: Change, error: type[AppError]
) -> None:
    # Không khóa FOR SHARE thì lệnh gán đọc bản trước khi sửa và gán thành công cho bộ phận
    # đã xóa, user đã đổi role hay bị khóa.
    result = await _assign_while_other_transaction_commits(engine, change)

    assert isinstance(result, error)


async def _remove_manager(engine: AsyncEngine, department_id: int, user_id: int) -> None:
    async with AsyncSession(engine) as session:
        await DepartmentService(session).remove_manager(department_id, user_id)


@pytest.mark.usefixtures("clean_after")
async def test_reassign_manager_while_other_admin_removes_it(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Gán lại người đã là manager, đúng lúc admin khác gỡ người đó. Dòng liên kết đã có không bị
    # khóa thì lệnh gỡ commit chen giữa lúc ghi và lúc đọc lại thời điểm gán: lệnh gán không còn
    # dòng để trả về (500).
    async with AsyncSession(engine) as setup:
        manager = await create_user(setup, role=UserRole.MANAGER)
        department = await create_department(setup, managers=[manager])
        department_id, user_id = department.id, manager.id
        await setup.commit()

    # Như SessionFactory của app: commit xong vẫn đọc được user để trả response.
    async with AsyncSession(engine, expire_on_commit=False) as session:
        execute = session.execute
        removal: asyncio.Task[None] | None = None

        async def execute_then_remove(
            statement: Executable, *args: Any, **kwargs: Any
        ) -> Result[Any]:
            nonlocal removal
            result = await execute(statement, *args, **kwargs)
            if removal is None and isinstance(statement, Insert):
                removal = asyncio.create_task(_remove_manager(engine, department_id, user_id))
                # Dòng không bị khóa thì lệnh gỡ commit xong trong lúc này; bị khóa thì lệnh gỡ
                # chờ lệnh gán commit.
                await asyncio.wait({removal}, timeout=LOCK_WAIT_SECONDS)
            return result

        monkeypatch.setattr(session, "execute", execute_then_remove)
        assigned = await DepartmentService(session).assign_manager(department_id, user_id)

    assert removal is not None
    await removal
    assert assigned.id == user_id
