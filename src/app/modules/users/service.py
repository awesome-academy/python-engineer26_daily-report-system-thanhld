from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import commit_unique
from app.core.security import hash_password
from app.modules.users.exceptions import EmailAlreadyExistsError
from app.modules.users.models import USER_EMAIL_UNIQUE_INDEX, User
from app.modules.users.repository import UserRepository
from app.modules.users.schemas import UserCreate, UserProfileUpdate


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
        self.users.add(user)
        await commit_unique(self.session, USER_EMAIL_UNIQUE_INDEX, EmailAlreadyExistsError())
        return user

    async def update_profile(self, user: User, data: UserProfileUpdate) -> User:
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(user, field, value)
        await self.session.commit()
        return user
