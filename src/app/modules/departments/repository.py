from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import Select, delete, exists, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import LIKE_ESCAPE_CHAR
from app.core.pagination import PageParams, paginate
from app.core.search import contains_pattern
from app.modules.departments.models import Department, DepartmentManager
from app.modules.users.models import User

# Sắp user theo họ tên không phân biệt hoa thường, không dấu. Collation của DB (C, hay musl trên
# image alpine) sắp theo byte: chữ thường, chữ có dấu đứng sau "Z" ("Bình, Zung, an, Ánh, Đặng").
# Trùng tên không dấu thì xét tên gốc rồi id để thứ tự cố định giữa các trang.
_BY_NAME = (func.immutable_unaccent(func.lower(User.full_name)), User.full_name, User.id)


class DepartmentRepository:
    """Truy vấn bộ phận, thành viên và manager. Mặc định bỏ qua bản ghi đã bị xóa mềm."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def _active(self) -> Select[Department]:
        return select(Department).where(Department.deleted_at.is_(None))

    async def search(
        self, params: PageParams, keyword: str | None
    ) -> tuple[Sequence[Department], int]:
        statement = self._active().order_by(Department.code)
        if keyword:
            # Tìm theo mã hoặc tên, không phân biệt hoa thường, không dấu ("ky thuat" khớp
            # "Kỹ thuật"). Mã chỉ có chữ không dấu nên không cần unaccent.
            pattern = contains_pattern(keyword)
            statement = statement.where(
                or_(
                    func.lower(Department.code).like(pattern, escape=LIKE_ESCAPE_CHAR),
                    func.immutable_unaccent(func.lower(Department.name)).like(
                        pattern, escape=LIKE_ESCAPE_CHAR
                    ),
                )
            )
        return await paginate(self.session, statement, params)

    async def get_by_id(self, department_id: int) -> Department | None:
        return await self.session.scalar(self._active().where(Department.id == department_id))

    async def get_by_id_for_update(self, department_id: int) -> Department | None:
        return await self.session.scalar(
            self._active().where(Department.id == department_id).with_for_update()
        )

    async def get_by_id_for_share(self, department_id: int) -> Department | None:
        # FOR SHARE: thao tác khác vẫn đọc, gán manager được; xóa, sửa bộ phận phải chờ.
        return await self.session.scalar(
            self._active().where(Department.id == department_id).with_for_update(read=True)
        )

    async def has_managed_department(self, user_id: int) -> bool:
        """User có đang là manager của bộ phận nào chưa bị xóa không."""
        managed = (
            exists()
            .where(DepartmentManager.user_id == user_id)
            .where(DepartmentManager.department_id == Department.id)
            .where(Department.deleted_at.is_(None))
        )
        return bool(await self.session.scalar(select(managed)))

    async def get_by_code(self, code: str) -> Department | None:
        return await self.session.scalar(
            self._active().where(func.lower(Department.code) == func.lower(code))
        )

    async def count_members(self, department_id: int) -> int:
        return (
            await self.session.scalar(
                select(func.count()).where(
                    User.department_id == department_id, User.deleted_at.is_(None)
                )
            )
            or 0
        )

    def members_statement(self, department_id: int) -> Select[User]:
        return (
            select(User)
            .where(User.department_id == department_id, User.deleted_at.is_(None))
            .order_by(*_BY_NAME)
        )

    async def get_manager_ids(self, department_id: int, user_ids: Sequence[int]) -> set[int]:
        """Trong `user_ids`, những ai là manager của bộ phận."""
        rows = await self.session.scalars(
            select(DepartmentManager.user_id).where(
                DepartmentManager.department_id == department_id,
                DepartmentManager.user_id.in_(user_ids),
            )
        )
        return set(rows)

    async def add_manager(self, department_id: int, user_id: int) -> datetime:
        """Gán manager, trả thời điểm gán. Đã là manager thì giữ thời điểm gán lần đầu."""
        # ON CONFLICT: hai request gán cùng một người chạy song song không thành lỗi trùng khóa.
        # DO UPDATE ghi lại chính giá trị cũ, không dùng DO NOTHING: dòng đã có bị khóa đến khi
        # commit và RETURNING luôn có một dòng. DO NOTHING không khóa, lệnh gỡ manager commit chen
        # giữa lúc ghi và lúc đọc lại thì không còn dòng để trả về.
        result = await self.session.execute(
            insert(DepartmentManager)
            .values(department_id=department_id, user_id=user_id)
            .on_conflict_do_update(
                index_elements=[DepartmentManager.department_id, DepartmentManager.user_id],
                set_={"assigned_at": DepartmentManager.assigned_at},
            )
            .returning(DepartmentManager.assigned_at)
        )
        return result.scalar_one()

    async def remove_manager(self, department_id: int, user_id: int) -> None:
        await self.session.execute(
            delete(DepartmentManager).where(
                DepartmentManager.department_id == department_id,
                DepartmentManager.user_id == user_id,
            )
        )

    async def remove_managers(self, department_id: int) -> None:
        await self.session.execute(
            delete(DepartmentManager).where(DepartmentManager.department_id == department_id)
        )

    def add(self, department: Department) -> None:
        self.session.add(department)
