import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import commit_unique
from app.modules.departments.exceptions import DepartmentCodeExistsError
from app.modules.departments.models import DEPARTMENT_CODE_UNIQUE_INDEX, Department
from app.modules.departments.repository import DepartmentRepository
from app.modules.departments.schemas import DepartmentCreate, DepartmentUpdate
from app.modules.departments.service import DepartmentService
from app.modules.users.models import USER_EMAIL_UNIQUE_INDEX, User
from tests.factories import create_department


@pytest.fixture
def code_check_misses(monkeypatch: pytest.MonkeyPatch) -> None:
    """Giả lập request song song: lúc kiểm tra, bộ phận cùng mã kia chưa được commit."""

    async def not_found(_: DepartmentRepository, __: str) -> Department | None:
        return None

    monkeypatch.setattr(DepartmentRepository, "get_by_code", not_found)


@pytest.mark.usefixtures("code_check_misses")
async def test_create_department_maps_concurrent_duplicate_to_code_exists(
    db_session: AsyncSession,
) -> None:
    await create_department(db_session, code="DEV")

    with pytest.raises(DepartmentCodeExistsError):
        await DepartmentService(db_session).create_department(
            DepartmentCreate(code="DEV", name="Phòng Phát triển")
        )


@pytest.mark.usefixtures("code_check_misses")
async def test_update_department_maps_concurrent_duplicate_to_code_exists(
    db_session: AsyncSession,
) -> None:
    await create_department(db_session, code="QA")
    department = await create_department(db_session, code="DEV")

    with pytest.raises(DepartmentCodeExistsError):
        await DepartmentService(db_session).update_department(
            department.id, DepartmentUpdate(code="QA")
        )


async def test_commit_unique_reraises_violation_of_other_constraint(
    db_session: AsyncSession,
) -> None:
    db_session.add_all(User(email="an@example.com", full_name="An") for _ in range(2))

    # Lỗi unique email không phải lỗi mã bộ phận: giữ nguyên IntegrityError, không đổi thành 409.
    with pytest.raises(IntegrityError, match=USER_EMAIL_UNIQUE_INDEX):
        await commit_unique(db_session, DEPARTMENT_CODE_UNIQUE_INDEX, DepartmentCodeExistsError())
