"""Băm mật khẩu (Argon2) và tạo, kiểm tra access token (JWT).

Băm và kiểm tra mật khẩu tốn CPU (khoảng vài chục ms), nên các hàm async ở đây chạy chúng
trong thread riêng để không chặn event loop.
"""

import asyncio
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import cache

import jwt
from pwdlib import PasswordHash

from app.core.config import get_settings
from app.core.exceptions import UnauthorizedError

ACCESS_TOKEN_TYPE = "access"  # noqa: S105

_password_hash = PasswordHash.recommended()


async def hash_password(password: str) -> str:
    return await asyncio.to_thread(_password_hash.hash, password)


async def verify_password(password: str, password_hash: str) -> bool:
    return await asyncio.to_thread(_password_hash.verify, password, password_hash)


@cache
def _dummy_password_hash() -> str:
    return _password_hash.hash("dummy-password-for-constant-time-check")


async def verify_dummy_password(password: str) -> None:
    """Gọi khi không tìm thấy user, để thời gian phản hồi giống khi sai mật khẩu.

    Tránh việc đoán email nào đã có tài khoản dựa vào thời gian phản hồi.
    """
    await verify_password(password, await asyncio.to_thread(_dummy_password_hash))


@dataclass(frozen=True)
class AccessToken:
    token: str
    expires_in: int


@dataclass(frozen=True)
class AccessTokenClaims:
    user_id: int
    role: str
    token_version: int
    jti: str


def create_access_token(*, user_id: int, role: str, token_version: int) -> AccessToken:
    settings = get_settings()
    now = datetime.now(UTC)
    expires_in = settings.access_token_expire_minutes * 60
    claims = {
        "sub": str(user_id),
        "role": role,
        "ver": token_version,
        "jti": uuid.uuid4().hex,
        "type": ACCESS_TOKEN_TYPE,
        "iat": now,
        "exp": now + timedelta(seconds=expires_in),
    }
    token = jwt.encode(claims, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    return AccessToken(token=token, expires_in=expires_in)


def decode_access_token(token: str) -> AccessTokenClaims:
    """Kiểm tra chữ ký, hạn dùng và loại token. Token không hợp lệ thì ném UnauthorizedError."""
    settings = get_settings()
    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["sub", "exp", "jti", "ver", "type"]},
        )
        if claims["type"] != ACCESS_TOKEN_TYPE:
            raise UnauthorizedError
        return AccessTokenClaims(
            user_id=int(claims["sub"]),
            role=str(claims["role"]),
            token_version=int(claims["ver"]),
            jti=str(claims["jti"]),
        )
    except (jwt.PyJWTError, KeyError, TypeError, ValueError) as exc:
        raise UnauthorizedError from exc
