from collections.abc import Sequence

from sqlalchemy import Select, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import PageParams, paginate
from app.modules.departments.models import Department, DepartmentManager
from app.modules.users.models import User

# Ký tự đặc biệt của LIKE: từ khóa "50%" phải tìm đúng chuỗi "50%", không phải "50" + bất kỳ.
_LIKE_ESCAPE = "\\"
_LIKE_SPECIAL = str.maketrans({char: _LIKE_ESCAPE + char for char in ("\\", "%", "_")})


class DepartmentRepository:
    """Truy vấn bảng departments. Mặc định bỏ qua bộ phận đã bị xóa mềm."""

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
            pattern = func.concat(
                "%", func.immutable_unaccent(func.lower(keyword.translate(_LIKE_SPECIAL))), "%"
            )
            statement = statement.where(
                or_(
                    func.lower(Department.code).like(pattern, escape=_LIKE_ESCAPE),
                    func.immutable_unaccent(func.lower(Department.name)).like(
                        pattern, escape=_LIKE_ESCAPE
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

    async def remove_managers(self, department_id: int) -> None:
        await self.session.execute(
            delete(DepartmentManager).where(DepartmentManager.department_id == department_id)
        )

    def add(self, department: Department) -> None:
        self.session.add(department)
