"""Dependency dùng chung cho các router."""

from collections.abc import Awaitable, Callable
from datetime import date
from typing import Annotated

from fastapi import Depends, Path
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import local_today
from app.core.database import get_db_session
from app.core.exceptions import ForbiddenError, UnauthorizedError
from app.core.redis import get_redis
from app.core.security import AccessTokenClaims, decode_access_token, oauth2_scheme
from app.core.validators import Id
from app.modules.auth.blacklist import is_session_blacklisted
from app.modules.users.models import User, UserRole
from app.modules.users.repository import UserRepository

DbSession = Annotated[AsyncSession, Depends(get_db_session)]
RedisClient = Annotated[Redis, Depends(get_redis)]
# Id trên URL, cùng ràng buộc với id trong body, query (xem Id).
IdPath = Annotated[Id, Path()]
# Hôm nay theo múi giờ nghiệp vụ. Nhận qua dependency để test cố định được ngày (mốc qua tháng).
Today = Annotated[date, Depends(local_today)]


async def get_token_claims(
    redis: RedisClient, token: Annotated[str | None, Depends(oauth2_scheme)]
) -> AccessTokenClaims:
    if not token:
        raise UnauthorizedError
    claims = decode_access_token(token)
    if await is_session_blacklisted(redis, claims.session_id):
        raise UnauthorizedError
    return claims


CurrentTokenClaims = Annotated[AccessTokenClaims, Depends(get_token_claims)]


async def get_current_user(session: DbSession, claims: CurrentTokenClaims) -> User:
    user = await UserRepository(session).get_by_id(claims.user_id)
    # token_version khác nghĩa là user đã đổi mật khẩu, bị khóa hoặc bị xóa sau khi cấp token.
    if user is None or not user.can_log_in or user.token_version != claims.token_version:
        raise UnauthorizedError
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_roles(*roles: UserRole) -> Callable[[User], Awaitable[User]]:
    """Tạo dependency chỉ cho user có một trong các role đi qua, role khác nhận 403.

    Role lấy từ user trong DB chứ không từ claim của token, nên admin đổi role thì có hiệu lực
    ngay, không phải chờ access token cũ hết hạn.
    """
    allowed = frozenset(roles)

    async def check_role(user: CurrentUser) -> User:
        if user.role not in allowed:
            raise ForbiddenError
        return user

    return check_role
