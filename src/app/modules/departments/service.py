from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import commit_unique
from app.modules.departments.exceptions import (
    DepartmentCodeExistsError,
    DepartmentNotEmptyError,
    DepartmentNotFoundError,
)
from app.modules.departments.models import DEPARTMENT_CODE_UNIQUE_INDEX, Department
from app.modules.departments.repository import DepartmentRepository
from app.modules.departments.schemas import (
    DepartmentCreate,
    DepartmentListParams,
    DepartmentUpdate,
)


class DepartmentService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.departments = DepartmentRepository(session)

    async def list_departments(
        self, params: DepartmentListParams
    ) -> tuple[Sequence[Department], int]:
        return await self.departments.search(params, params.keyword)

    async def get_department(self, department_id: int) -> Department:
        department = await self.departments.get_by_id(department_id)
        if department is None:
            raise DepartmentNotFoundError
        return department

    async def create_department(self, data: DepartmentCreate) -> Department:
        if await self.departments.get_by_code(data.code) is not None:
            raise DepartmentCodeExistsError
        department = Department(**data.model_dump())
        self.departments.add(department)
        await commit_unique(self.session, DEPARTMENT_CODE_UNIQUE_INDEX, DepartmentCodeExistsError())
        return department

    async def update_department(self, department_id: int, data: DepartmentUpdate) -> Department:
        # Khóa dòng như khi xóa: lệnh xóa commit chen giữa thì lệnh sửa chờ xong, đọc lại thấy bộ
        # phận đã xóa và trả 404, thay vì ghi vào bộ phận đã xóa rồi trả 200.
        department = await self.departments.get_by_id_for_update(department_id)
        if department is None:
            raise DepartmentNotFoundError
        changes = data.model_dump(exclude_unset=True)
        if "code" in changes:
            other = await self.departments.get_by_code(changes["code"])
            if other is not None and other.id != department.id:
                # Nhả khóa dòng ngay, không giữ đến khi session đóng.
                await self.session.rollback()
                raise DepartmentCodeExistsError
        for field, value in changes.items():
            setattr(department, field, value)
        await commit_unique(self.session, DEPARTMENT_CODE_UNIQUE_INDEX, DepartmentCodeExistsError())
        # updated_at do DB đặt lúc UPDATE (onupdate), nạp lại để response trả giá trị mới.
        await self.session.refresh(department)
        return department

    async def delete_department(self, department_id: int) -> None:
        """Xóa mềm. Bộ phận còn thành viên (user chưa bị xóa) thì không cho xóa.

        Khóa dòng bộ phận để hai lệnh xóa cùng lúc không cùng đi qua bước kiểm tra. Liên kết
        manager bị xóa luôn: bộ phận đã xóa không còn ai quản lý, giống ON DELETE CASCADE khi
        xóa cứng.
        """
        department = await self.departments.get_by_id_for_update(department_id)
        if department is None:
            raise DepartmentNotFoundError
        member_count = await self.departments.count_members(department_id)
        if member_count:
            # Nhả khóa dòng ngay, không giữ đến khi session đóng.
            await self.session.rollback()
            raise DepartmentNotEmptyError(member_count)
        await self.departments.remove_managers(department_id)
        department.deleted_at = datetime.now(UTC)
        await self.session.commit()
