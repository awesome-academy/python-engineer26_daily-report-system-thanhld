from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import PageParams, paginate
from app.modules.users.models import User, UserRole, full_name_or_email_matches, order_by_full_name


class UserRepository:
    """Truy vấn bảng users. Mặc định bỏ qua user đã bị xóa mềm."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, user_id: int) -> User | None:
        return await self.session.scalar(
            select(User).where(User.id == user_id, User.deleted_at.is_(None))
        )

    async def get_by_id_for_update(self, user_id: int) -> User | None:
        # populate_existing: user đã có trong session (CurrentUser) được nạp lại dữ liệu mới nhất
        # sau khi chờ khóa, không giữ bản đọc trước đó.
        return await self.session.scalar(
            select(User)
            .where(User.id == user_id, User.deleted_at.is_(None))
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    async def get_by_id_for_share(self, user_id: int) -> User | None:
        # FOR SHARE: đổi role, khóa, xóa user phải chờ thao tác đang dựa vào các giá trị này xong.
        return await self.session.scalar(
            select(User)
            .where(User.id == user_id, User.deleted_at.is_(None))
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )

    async def lock_active_admin_ids(self) -> list[int]:
        """Khóa dòng mọi admin đăng nhập được, theo thứ tự id, trả về id của họ.

        Hai request cùng gỡ quyền admin (khóa, hạ role, xóa) đều phải đi qua đây trước, nên chạy
        lần lượt: request sau chờ request trước commit rồi mới đếm. Khóa theo thứ tự id để hai
        request không giữ khóa chéo nhau (deadlock).
        """
        rows = await self.session.scalars(
            select(User.id)
            .where(
                User.role == UserRole.ADMIN,
                User.is_active.is_(True),
                User.password_hash.is_not(None),
                User.deleted_at.is_(None),
            )
            .order_by(User.id)
            .with_for_update()
        )
        return list(rows)

    async def get_by_email(self, email: str) -> User | None:
        return await self.session.scalar(
            select(User).where(func.lower(User.email) == email.lower(), User.deleted_at.is_(None))
        )

    async def search(
        self,
        params: PageParams,
        *,
        keyword: str | None = None,
        role: UserRole | None = None,
        department_id: int | None = None,
    ) -> tuple[Sequence[User], int]:
        statement = select(User).where(User.deleted_at.is_(None)).order_by(User.id)
        if keyword:
            statement = statement.where(full_name_or_email_matches(keyword))
        if role is not None:
            statement = statement.where(User.role == role)
        if department_id is not None:
            statement = statement.where(User.department_id == department_id)
        return await paginate(self.session, statement, params)

    async def search_member_candidates(
        self, params: PageParams, keyword: str | None
    ) -> tuple[Sequence[User], int]:
        """Ứng viên manager thêm được vào bộ phận (`User.is_member_candidate`), sắp theo họ tên."""
        statement = select(User).where(User.is_member_candidate).order_by(*order_by_full_name())
        if keyword:
            statement = statement.where(full_name_or_email_matches(keyword))
        return await paginate(self.session, statement, params)

    async def get_many_for_update(self, user_ids: Sequence[int]) -> Sequence[User]:
        """Khóa dòng các user chưa xóa trong `user_ids`, theo thứ tự id.

        Hai request khóa chung vài user (hai manager cùng thêm một nhóm người) luôn khóa theo cùng
        thứ tự, nên không giữ khóa chéo nhau (deadlock).
        """
        rows = await self.session.scalars(
            select(User)
            .where(User.id.in_(user_ids), User.deleted_at.is_(None))
            .order_by(User.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return rows.all()

    def add(self, user: User) -> None:
        self.session.add(user)
