from typing import Annotated

from fastapi import Depends

from app.api.deps import DbSession, RedisClient
from app.modules.auth.service import AuthService


def get_auth_service(session: DbSession, redis: RedisClient) -> AuthService:
    return AuthService(session, redis)


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]
