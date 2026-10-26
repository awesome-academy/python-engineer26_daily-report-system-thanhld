from typing import Annotated

from fastapi import Depends

from app.api.deps import DbSession
from app.modules.auth.service import AuthService


def get_auth_service(session: DbSession) -> AuthService:
    return AuthService(session)


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]
