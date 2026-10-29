from typing import Annotated

from fastapi import Depends

from app.api.deps import DbSession
from app.modules.users.service import UserService


def get_user_service(session: DbSession) -> UserService:
    return UserService(session)


UserServiceDep = Annotated[UserService, Depends(get_user_service)]
