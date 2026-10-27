from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.modules.users.exceptions import EmailAlreadyExistsError
from app.modules.users.models import USER_EMAIL_UNIQUE_INDEX, User
from app.modules.users.repository import UserRepository
from app.modules.users.schemas import UserCreate


class UserService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.users = UserRepository(session)

    async def create_user(self, data: UserCreate) -> User:
        if await self.users.get_by_email(data.email) is not None:
            raise EmailAlreadyExistsError
        user = User(
            email=data.email,
            full_name=data.full_name,
            role=data.role,
            password_hash=await hash_password(data.password),
        )
        try:
            await self.users.add(user)
        except IntegrityError as exc:
            # Hai lệnh tạo cùng email chạy song song đều qua được bước kiểm tra ở trên.
            if USER_EMAIL_UNIQUE_INDEX in str(exc.orig):
                raise EmailAlreadyExistsError from exc
            raise
        await self.session.commit()
        return user
