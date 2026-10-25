"""Hàm tạo dữ liệu mẫu cho test."""

from datetime import UTC, datetime
from itertools import count

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password
from app.modules.users.models import User, UserRole

DEFAULT_PASSWORD = "Matkhau@123"

_sequence = count(1)
# Băm Argon2 tốn thời gian, nên mỗi mật khẩu chỉ băm một lần cho cả bộ test.
_password_hashes: dict[str, str] = {}


async def create_user(
    session: AsyncSession,
    *,
    email: str | None = None,
    full_name: str = "Nguyễn Văn An",
    password: str | None = DEFAULT_PASSWORD,
    role: UserRole = UserRole.USER,
    is_active: bool = True,
    deleted: bool = False,
) -> User:
    password_hash = None
    if password is not None:
        if password not in _password_hashes:
            _password_hashes[password] = await hash_password(password)
        password_hash = _password_hashes[password]

    user = User(
        email=email or f"user{next(_sequence)}@example.com",
        full_name=full_name,
        password_hash=password_hash,
        role=role,
        is_active=is_active,
        deleted_at=datetime.now(UTC) if deleted else None,
    )
    session.add(user)
    await session.flush()
    return user


def auth_headers(user: User) -> dict[str, str]:
    token = create_access_token(user_id=user.id, role=user.role, token_version=user.token_version)
    return {"Authorization": f"Bearer {token.token}"}
