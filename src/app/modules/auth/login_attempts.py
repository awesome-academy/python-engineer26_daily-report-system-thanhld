"""Đếm số lần thử đăng nhập theo email trên Redis để khóa tạm khi bị dò mật khẩu."""

import hashlib

from redis.asyncio import Redis

from app.core.constants import (
    LOGIN_ATTEMPT_WINDOW_MINUTES,
    LOGIN_MAX_FAILED_ATTEMPTS,
    REDIS_LOGIN_ATTEMPTS_PREFIX,
)
from app.modules.auth.exceptions import TooManyAttemptsError


def _key(email: str) -> str:
    # Băm để key có độ dài cố định (form không giới hạn độ dài username) và không chứa email.
    digest = hashlib.sha256(email.lower().encode()).hexdigest()
    return f"{REDIS_LOGIN_ATTEMPTS_PREFIX}{digest}"


class LoginAttempts:
    """Cửa sổ cố định: tính từ lần thử đầu tiên, đăng nhập đúng thì xóa bộ đếm.

    Đếm cả email không tồn tại, để việc bị khóa không cho biết email nào có tài khoản.
    """

    def __init__(self, redis: Redis) -> None:
        self.redis = redis

    async def register(self, email: str) -> None:
        """Ghi nhận một lần thử. Đã quá giới hạn thì ném TooManyAttemptsError.

        Đếm trước khi kiểm tra mật khẩu: các request song song không vượt được giới hạn, và
        request bị khóa không tốn thời gian băm Argon2.
        """
        key = _key(email)
        async with self.redis.pipeline(transaction=True) as pipe:
            pipe.set(key, 0, ex=LOGIN_ATTEMPT_WINDOW_MINUTES * 60, nx=True)
            pipe.incr(key)
            pipe.ttl(key)
            _, attempts, ttl = await pipe.execute()
        if attempts > LOGIN_MAX_FAILED_ATTEMPTS:
            raise TooManyAttemptsError(retry_after=ttl)

    async def reset(self, email: str) -> None:
        await self.redis.delete(_key(email))
