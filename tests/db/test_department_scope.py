"""Phạm vi manager dạng câu truy vấn con, để Ngày 6 lọc danh sách bộ phận, nhân viên, báo cáo."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.departments.repository import DepartmentRepository
from app.modules.users.models import UserRole
from tests.factories import create_department, create_user


async def test_managed_department_ids_covers_only_active_departments_of_manager(
    db_session: AsyncSession,
) -> None:
    manager = await create_user(db_session, role=UserRole.MANAGER)
    other_manager = await create_user(db_session, role=UserRole.MANAGER)
    first = await create_department(db_session, managers=[manager])
    shared = await create_department(db_session, managers=[manager, other_manager])
    await create_department(db_session, managers=[manager], deleted=True)
    await create_department(db_session, managers=[other_manager])
    # Thành viên bộ phận nhưng không được gán làm manager: không tính vào phạm vi.
    manager.department_id = (await create_department(db_session)).id
    await db_session.flush()

    statement = DepartmentRepository(db_session).managed_department_ids(manager.id)
    ids = await db_session.scalars(statement)

    assert set(ids) == {first.id, shared.id}
