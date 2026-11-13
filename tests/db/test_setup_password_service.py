"""Đặt mật khẩu lần đầu (S2) với nhiều request thật chạy song song."""

import asyncio

import pytest
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core.security import verify_password
from app.modules.auth.exceptions import SetupTokenInvalidError
from app.modules.auth.schemas import PasswordSetup
from app.modules.auth.service import AuthService
from app.modules.users.models import User
from tests.factories import create_setup_token, create_user

PASSWORDS = ("MatKhauMot@2026", "MatKhauHai@2026")


@pytest.mark.usefixtures("clean_after")
async def test_same_link_used_concurrently_sets_password_once(
    engine: AsyncEngine, redis: Redis
) -> None:
    # Không khóa rồi kiểm tra lại thì cả hai cùng thấy token chưa dùng: cả hai thành công, người
    # cầm link bị lộ ghi đè được mật khẩu chủ tài khoản vừa đặt.
    async with AsyncSession(engine) as session:
        user = await create_user(session, password=None)
        token = await create_setup_token(session, user)
        user_id = user.id
        await session.commit()

    async def use_link(password: str) -> None:
        async with AsyncSession(engine) as session:
            await AuthService(session, redis).setup_password(
                PasswordSetup(token=token, password=password)
            )

    results = await asyncio.gather(*(use_link(p) for p in PASSWORDS), return_exceptions=True)

    assert sum(result is None for result in results) == 1
    assert sum(isinstance(result, SetupTokenInvalidError) for result in results) == 1
    winner = PASSWORDS[results.index(None)]
    async with AsyncSession(engine) as session:
        password_hash = await session.scalar(select(User.password_hash).where(User.id == user_id))
    assert password_hash is not None
    assert await verify_password(winner, password_hash)
