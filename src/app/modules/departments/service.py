from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import commit_unique
from app.core.pagination import Page, PageParams, paginate
from app.modules.departments.exceptions import (
    DepartmentCodeExistsError,
    DepartmentNotEmptyError,
    DepartmentNotFoundError,
    EmployeeRoleRequiredError,
    InvalidMemberCandidateError,
    ManagerRoleRequiredError,
)
from app.modules.departments.models import (
    DEPARTMENT_CODE_UNIQUE_INDEX,
    Department,
    DepartmentManager,
)
from app.modules.departments.repository import DepartmentRepository
from app.modules.departments.schemas import (
    DepartmentCreate,
    DepartmentDetailOut,
    DepartmentListParams,
    DepartmentManagerOut,
    DepartmentMemberListParams,
    DepartmentMemberOut,
    DepartmentOut,
    DepartmentUpdate,
    MemberCandidateListParams,
)
from app.modules.users.exceptions import UserInactiveError, UserNotFoundError
from app.modules.users.models import User, UserRole
from app.modules.users.repository import UserRepository


def _manager_out(link: DepartmentManager) -> DepartmentManagerOut:
    # link.user đã nạp sẵn trong managers_statement (contains_eager).
    return DepartmentManagerOut(
        id=link.user.id,
        email=link.user.email,
        full_name=link.user.full_name,
        assigned_at=link.assigned_at,
    )


class DepartmentService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.departments = DepartmentRepository(session)
        self.users = UserRepository(session)

    async def list_departments(
        self, params: DepartmentListParams
    ) -> tuple[Sequence[Department], int]:
        return await self.departments.search(params, params.keyword)

    async def list_managed_departments(
        self, manager_id: int, params: DepartmentListParams
    ) -> tuple[Sequence[Department], int]:
        return await self.departments.search(params, params.keyword, manager_id=manager_id)

    async def get_department(self, department_id: int) -> Department:
        department = await self.departments.get_by_id(department_id)
        if department is None:
            raise DepartmentNotFoundError
        return department

    async def get_managed_department(
        self, manager_id: int, department_id: int, *, for_share: bool = False
    ) -> Department:
        """Policy phạm vi của manager: bộ phận phải còn và do manager này quản lý.

        Ngoài phạm vi trả đúng lỗi của bộ phận không tồn tại, để manager không dò được id nào là
        bộ phận có thật. Role MANAGER đã kiểm tra ở nhóm router `/manager`, ở đây chỉ xét phạm vi.

        Endpoint chỉ đọc không cần khóa. Endpoint ghi vào bộ phận (thêm, gỡ thành viên) truyền
        `for_share=True` để khóa `FOR SHARE` đến khi commit như `assign_manager`: admin xóa bộ
        phận chen giữa thì phải chờ, rồi thấy thành viên vừa thêm và trả `DEPARTMENT_NOT_EMPTY`.
        """
        department = await self.departments.get_managed_by_id(
            department_id, manager_id, for_share=for_share
        )
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

    async def get_department_detail(self, department: Department) -> DepartmentDetailOut:
        """Bộ phận kèm manager và số thành viên: thêm đúng hai câu SQL, không phụ thuộc số người."""
        links = await self.session.scalars(self.departments.managers_statement(department.id))
        return DepartmentDetailOut(
            **DepartmentOut.model_validate(department).model_dump(),
            managers=[_manager_out(link) for link in links],
            member_count=await self.departments.count_members(department.id),
        )

    async def list_members(
        self, department_id: int, params: PageParams
    ) -> Page[DepartmentMemberOut]:
        await self.get_department(department_id)
        return await self._members_page(department_id, params)

    async def list_managed_members(
        self, department: Department, params: DepartmentMemberListParams
    ) -> Page[DepartmentMemberOut]:
        # Bộ phận đã qua policy phạm vi (ManagedDepartment), không đọc lại.
        return await self._members_page(department.id, params, params.keyword)

    async def _members_page(
        self, department_id: int, params: PageParams, keyword: str | None = None
    ) -> Page[DepartmentMemberOut]:
        # Ba câu SQL (đếm, trang thành viên, cờ manager của cả trang) dù trang có bao nhiêu người.
        members, total = await paginate(
            self.session, self.departments.members_statement(department_id, keyword), params
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
        return Page.build([_manager_out(link) for link in links], total=total, params=params)

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

    async def list_candidates(
        self, params: MemberCandidateListParams
    ) -> tuple[Sequence[User], int]:
        return await self.users.search_member_candidates(params, params.keyword)

    async def add_members(self, department_id: int, user_ids: Sequence[int]) -> None:
        """Thêm nhân viên vào bộ phận của manager. Gửi lại người đã là thành viên thì không lỗi.

        Bộ phận đã được khóa `FOR SHARE` (`ManagedDepartmentForShare`). Ở đây khóa dòng các user
        rồi mới xét: hai manager của hai bộ phận cùng thêm một người thì lệnh sau chờ lệnh trước
        commit, đọc lại thấy người đó đã thuộc bộ phận khác và báo lỗi, không ghi đè. Còn id sai
        thì không thêm ai, để client sửa rồi gửi lại cả danh sách.
        """
        users = {user.id: user for user in await self.users.get_many_for_update(user_ids)}
        invalid_ids = [
            user_id
            for user_id in user_ids
            if (user := users.get(user_id)) is None
            or not (user.is_member_candidate or user.department_id == department_id)
        ]
        if invalid_ids:
            # Nhả khóa dòng ngay, không giữ đến khi session đóng.
            await self.session.rollback()
            raise InvalidMemberCandidateError(invalid_ids)
        for user in users.values():
            user.department_id = department_id
        await self.session.commit()

    async def remove_member(self, department_id: int, user_id: int) -> None:
        """Gỡ nhân viên khỏi bộ phận, tài khoản giữ nguyên. Không còn là thành viên thì không lỗi.

        Khóa dòng user để không chạy xen với admin đổi bộ phận, đổi role của người đó: user đã
        được admin chuyển sang bộ phận khác thì không bị gỡ nhầm.
        """
        user = await self.users.get_by_id_for_update(user_id)
        if user is None:
            await self.session.rollback()
            raise UserNotFoundError
        if user.department_id != department_id:
            await self.session.rollback()
            return
        if user.role is not UserRole.USER:
            await self.session.rollback()
            raise EmployeeRoleRequiredError
        user.department_id = None
        await self.session.commit()
