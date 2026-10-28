"""Băm mật khẩu (Argon2) và tạo, kiểm tra access token (JWT).

Băm và kiểm tra mật khẩu tốn CPU (khoảng vài chục ms), nên các hàm async ở đây chạy chúng
trong thread riêng để không chặn event loop.
"""

import asyncio
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import cache
from typing import Any

import jwt
from fastapi.security import OAuth2PasswordBearer
from pwdlib import PasswordHash

from app.core.config import get_settings
from app.core.exceptions import UnauthorizedError

ACCESS_TOKEN_TYPE = "access"  # noqa: S105
REFRESH_TOKEN_TYPE = "refresh"  # noqa: S105

# Đọc token từ header "Authorization: Bearer ...". tokenUrl là endpoint nút Authorize gọi.
# auto_error=False: thiếu token thì tự trả lỗi theo format chung thay vì lỗi của FastAPI.
oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl=f"{get_settings().api_v1_prefix}/auth/login", auto_error=False
)

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
    # Mã phiên đăng nhập, giữ nguyên qua các lần refresh: đăng xuất thu hồi cả phiên.
    session_id: str


@dataclass(frozen=True)
class IssuedRefreshToken:
    token: str
    jti: str
    expires_at: datetime


@dataclass(frozen=True)
class RefreshTokenClaims:
    user_id: int
    token_version: int
    jti: str


def create_access_token(
    *, user_id: int, role: str, token_version: int, session_id: str
) -> AccessToken:
    settings = get_settings()
    now = datetime.now(UTC)
    expires_in = settings.access_token_expire_minutes * 60
    claims = {
        "sub": str(user_id),
        "role": role,
        "ver": token_version,
        "jti": uuid.uuid4().hex,
        "sid": session_id,
        "type": ACCESS_TOKEN_TYPE,
        "iat": now,
        "exp": now + timedelta(seconds=expires_in),
    }
    token = jwt.encode(claims, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    return AccessToken(token=token, expires_in=expires_in)


def create_refresh_token(*, user_id: int, token_version: int) -> IssuedRefreshToken:
    settings = get_settings()
    now = datetime.now(UTC)
    jti = uuid.uuid4().hex
    expires_at = now + timedelta(days=settings.refresh_token_expire_days)
    claims = {
        "sub": str(user_id),
        "ver": token_version,
        "jti": jti,
        "type": REFRESH_TOKEN_TYPE,
        "iat": now,
        "exp": expires_at,
    }
    token = jwt.encode(claims, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    return IssuedRefreshToken(token=token, jti=jti, expires_at=expires_at)


def _decode_token(token: str, token_type: str, *required: str) -> dict[str, Any]:
    """Kiểm tra chữ ký, hạn dùng và loại token: access token không dùng thay refresh token được."""
    settings = get_settings()
    claims: dict[str, Any] = jwt.decode(
        token,
        settings.jwt_secret_key,
        algorithms=[settings.jwt_algorithm],
        options={"require": ["sub", "exp", "jti", "ver", "type", *required]},
    )
    if claims["type"] != token_type:
        raise UnauthorizedError
    return claims


def decode_access_token(token: str) -> AccessTokenClaims:
    """Token không hợp lệ thì ném UnauthorizedError."""
    try:
        claims = _decode_token(token, ACCESS_TOKEN_TYPE, "role", "sid")
        return AccessTokenClaims(
            user_id=int(claims["sub"]),
            role=str(claims["role"]),
            token_version=int(claims["ver"]),
            jti=str(claims["jti"]),
            session_id=str(claims["sid"]),
        )
    except (jwt.PyJWTError, KeyError, TypeError, ValueError) as exc:
        raise UnauthorizedError from exc


def decode_refresh_token(token: str) -> RefreshTokenClaims:
    """Token không hợp lệ thì ném UnauthorizedError."""
    try:
        claims = _decode_token(token, REFRESH_TOKEN_TYPE)
        return RefreshTokenClaims(
            user_id=int(claims["sub"]),
            token_version=int(claims["ver"]),
            jti=str(claims["jti"]),
        )
    except (jwt.PyJWTError, KeyError, TypeError, ValueError) as exc:
        raise UnauthorizedError from exc
