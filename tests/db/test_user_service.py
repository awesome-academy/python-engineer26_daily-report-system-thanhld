import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.users.exceptions import EmailAlreadyExistsError
from app.modules.users.models import User
from app.modules.users.repository import UserRepository
from app.modules.users.schemas import UserCreate
from app.modules.users.service import UserService
from tests.factories import DEFAULT_PASSWORD, create_user


def new_user(email: str) -> UserCreate:
    return UserCreate(email=email, full_name="Nguyễn Văn An", password=DEFAULT_PASSWORD)


async def test_create_user_rejects_email_differing_only_in_case(db_session: AsyncSession) -> None:
    await create_user(db_session, email="an@example.com")

    with pytest.raises(EmailAlreadyExistsError):
        await UserService(db_session).create_user(new_user("An@Example.com"))


async def test_create_user_maps_concurrent_duplicate_to_email_already_exists(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    await create_user(db_session, email="an@example.com")

    # Giả lập lệnh tạo song song: lúc kiểm tra, user kia chưa được insert.
    async def not_found(_: UserRepository, __: str) -> User | None:
        return None

    monkeypatch.setattr(UserRepository, "get_by_email", not_found)

    with pytest.raises(EmailAlreadyExistsError):
        await UserService(db_session).create_user(new_user("an@example.com"))
