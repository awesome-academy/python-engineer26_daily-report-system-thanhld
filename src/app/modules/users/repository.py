from collections.abc import Sequence

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import LIKE_ESCAPE_CHAR
from app.core.pagination import PageParams, paginate
from app.core.search import contains_pattern
from app.modules.users.models import User, UserRole


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
            pattern = contains_pattern(keyword)
            # Cùng biểu thức với GIN index ix_users_full_name_search: "nguyen" khớp "Nguyễn".
            name_matches = func.immutable_unaccent(func.lower(User.full_name)).like(
                pattern, escape=LIKE_ESCAPE_CHAR
            )
            email_matches = func.lower(User.email).like(pattern, escape=LIKE_ESCAPE_CHAR)
            statement = statement.where(or_(name_matches, email_matches))
        if role is not None:
            statement = statement.where(User.role == role)
        if department_id is not None:
            statement = statement.where(User.department_id == department_id)
        return await paginate(self.session, statement, params)

    def add(self, user: User) -> None:
        self.session.add(user)
