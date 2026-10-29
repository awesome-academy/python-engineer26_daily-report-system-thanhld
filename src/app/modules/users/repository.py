from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.users.models import User


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

    async def add(self, user: User) -> User:
        self.session.add(user)
        await self.session.flush()
        return user
