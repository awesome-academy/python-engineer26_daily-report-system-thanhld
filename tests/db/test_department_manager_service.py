import asyncio
from collections.abc import Callable

import pytest
from sqlalchemy import Update, func, select, update
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
