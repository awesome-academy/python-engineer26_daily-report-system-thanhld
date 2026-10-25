"""Dependency dùng chung cho các router."""

from typing import Annotated

from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.core.exceptions import UnauthorizedError
from app.core.redis import get_redis
from app.core.security import decode_access_token
from app.modules.users.models import User
from app.modules.users.repository import UserRepository

DbSession = Annotated[AsyncSession, Depends(get_db_session)]
RedisClient = Annotated[Redis, Depends(get_redis)]

# auto_error=False: thiếu token thì tự trả lỗi theo format chung thay vì lỗi mặc định của FastAPI.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


async def get_current_user(
    session: DbSession, token: Annotated[str | None, Depends(oauth2_scheme)]
) -> User:
    if not token:
        raise UnauthorizedError
    claims = decode_access_token(token)
    user = await UserRepository(session).get_by_id(claims.user_id)
    # token_version khác nghĩa là user đã đổi mật khẩu, bị khóa hoặc bị xóa sau khi cấp token.
    if user is None or not user.can_log_in or user.token_version != claims.token_version:
        raise UnauthorizedError
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
