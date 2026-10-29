import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import BIGINT_MAX
from app.core.exceptions import AppError
from app.modules.departments.exceptions import DepartmentNotFoundError, ManagerRoleRequiredError
from app.modules.departments.service import DepartmentService
from app.modules.users.exceptions import UserInactiveError, UserNotFoundError
from app.modules.users.models import UserRole
from tests.factories import create_department, create_user


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
