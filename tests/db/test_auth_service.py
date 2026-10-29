from typing import Any

import pytest
from redis.asyncio import Redis
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import UnauthorizedError
from app.core.security import verify_password
from app.modules.auth.service import AuthService
from app.modules.users.models import User
from app.modules.users.schemas import PasswordChange
from tests.factories import DEFAULT_PASSWORD, create_user


@pytest.mark.parametrize(
    "change",
    [
        pytest.param({"token_version": User.token_version + 1}, id="sessions-revoked"),
        pytest.param({"is_active": False}, id="deactivated"),
    ],
)
async def test_change_password_rejects_session_ended_while_waiting_for_lock(
    db_session: AsyncSession, redis: Redis, change: dict[str, Any]
) -> None:
    user = await create_user(db_session)
    # Giả lập request khác (đổi mật khẩu, admin khóa tài khoản, phát hiện token bị lộ) commit trong
    # lúc request này chờ khóa dòng: DB đã đổi, user trong session vẫn là bản đọc lúc xác thực.
    await db_session.execute(
        update(User)
        .where(User.id == user.id)
        .values(**change)
        .execution_options(synchronize_session=False)
    )
    await db_session.commit()

    with pytest.raises(UnauthorizedError):
        await AuthService(db_session, redis).change_password(
            user,
            "session",
            PasswordChange(current_password=DEFAULT_PASSWORD, new_password="MatKhauMoi#2026"),
        )

    await db_session.refresh(user)
    assert user.password_hash is not None
    assert await verify_password(DEFAULT_PASSWORD, user.password_hash)
