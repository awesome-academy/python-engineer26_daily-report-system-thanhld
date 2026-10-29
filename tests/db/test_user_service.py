import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.users.exceptions import EmailAlreadyExistsError
from app.modules.users.models import User, UserRole
from app.modules.users.repository import UserRepository
from app.modules.users.schemas import AdminUserUpdate, UserCreate
from app.modules.users.service import UserService
from tests.factories import DEFAULT_PASSWORD, create_user


async def no_user_with_email(_: UserRepository, __: str) -> User | None:
    return None


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
    monkeypatch.setattr(UserRepository, "get_by_email", no_user_with_email)

    with pytest.raises(EmailAlreadyExistsError):
        await UserService(db_session).create_user(new_user("an@example.com"))


async def test_update_by_admin_maps_concurrent_duplicate_email_to_email_already_exists(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin = await create_user(db_session, role=UserRole.ADMIN)
    await create_user(db_session, email="binh@example.com")
    user = await create_user(db_session, email="an@example.com")
    # Giả lập request khác đổi sang cùng email: lúc kiểm tra, email đó chưa có ai dùng.
    monkeypatch.setattr(UserRepository, "get_by_email", no_user_with_email)

    with pytest.raises(EmailAlreadyExistsError):
        await UserService(db_session).update_by_admin(
            admin, user.id, AdminUserUpdate(email="binh@example.com")
        )
