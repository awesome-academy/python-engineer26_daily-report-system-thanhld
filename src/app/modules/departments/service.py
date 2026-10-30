from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import commit_unique
from app.core.pagination import Page, PageParams, paginate
from app.modules.departments.exceptions import (
    DepartmentCodeExistsError,
    DepartmentNotEmptyError,
    DepartmentNotFoundError,
    ManagerRoleRequiredError,
)
from app.modules.departments.models import DEPARTMENT_CODE_UNIQUE_INDEX, Department
from app.modules.departments.repository import DepartmentRepository
from app.modules.departments.schemas import (
    DepartmentCreate,
    DepartmentListParams,
    DepartmentManagerOut,
    DepartmentMemberOut,
    DepartmentUpdate,
)
from app.modules.users.exceptions import UserInactiveError, UserNotFoundError
from app.modules.users.models import UserRole
from app.modules.users.repository import UserRepository


class DepartmentService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.departments = DepartmentRepository(session)
        self.users = UserRepository(session)

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

    async def list_members(
        self, department_id: int, params: PageParams
    ) -> Page[DepartmentMemberOut]:
        await self.get_department(department_id)
        members, total = await paginate(
            self.session, self.departments.members_statement(department_id), params
        )
        manager_ids = await self.departments.get_manager_ids(
            department_id, [member.id for member in members]
        )
        items = [
            DepartmentMemberOut(
                id=member.id,
                email=member.email,
                full_name=member.full_name,
                role=member.role,
                is_active=member.is_active,
                is_manager=member.id in manager_ids,
            )
            for member in members
        ]
        return Page.build(items, total=total, params=params)

    async def list_managers(
        self, department_id: int, params: PageParams
    ) -> Page[DepartmentManagerOut]:
        await self.get_department(department_id)
        links, total = await paginate(
            self.session, self.departments.managers_statement(department_id), params
        )
        items = [
            DepartmentManagerOut(
                id=link.user.id,
                email=link.user.email,
                full_name=link.user.full_name,
                assigned_at=link.assigned_at,
            )
            for link in links
        ]
        return Page.build(items, total=total, params=params)

    async def assign_manager(self, department_id: int, user_id: int) -> DepartmentManagerOut:
        """Gán manager cho bộ phận. Người đã là manager thì giữ nguyên, không báo lỗi.

        Khóa FOR SHARE bộ phận và user đến khi commit: trong lúc gán, admin khác không xóa được
        bộ phận, không đổi được role hay khóa được user, nên điều kiện vừa kiểm tra vẫn đúng.
        Mọi nhánh lỗi rollback trước khi raise để nhả khóa ngay.
        """
        if await self.departments.get_by_id_for_share(department_id) is None:
            await self.session.rollback()
            raise DepartmentNotFoundError
        user = await self.users.get_by_id_for_share(user_id)
        if user is None:
            await self.session.rollback()
            raise UserNotFoundError
        if user.role is not UserRole.MANAGER:
            await self.session.rollback()
            raise ManagerRoleRequiredError
        if not user.is_active:
            await self.session.rollback()
            raise UserInactiveError

        assigned_at = await self.departments.add_manager(department_id, user_id)
        await self.session.commit()
        return DepartmentManagerOut(
            id=user.id, email=user.email, full_name=user.full_name, assigned_at=assigned_at
        )

    async def remove_manager(self, department_id: int, user_id: int) -> None:
        """Gỡ manager khỏi bộ phận. Người không phải manager của bộ phận thì không có gì để gỡ.

        User không tồn tại thì 404 như khi gán: id gõ nhầm không được trả 204 như đã gỡ xong.
        """
        await self.get_department(department_id)
        if await self.users.get_by_id(user_id) is None:
            raise UserNotFoundError
        await self.departments.remove_manager(department_id, user_id)
        await self.session.commit()
