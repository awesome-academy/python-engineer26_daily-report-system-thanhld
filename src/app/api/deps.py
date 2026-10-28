"""Dependency dùng chung cho các router."""

from typing import Annotated

from fastapi import Depends
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.core.exceptions import UnauthorizedError
from app.core.redis import get_redis
from app.core.security import AccessTokenClaims, decode_access_token, oauth2_scheme
from app.modules.auth.blacklist import is_session_blacklisted
from app.modules.users.models import User
from app.modules.users.repository import UserRepository

DbSession = Annotated[AsyncSession, Depends(get_db_session)]
RedisClient = Annotated[Redis, Depends(get_redis)]


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
