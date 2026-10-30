from typing import Annotated

from fastapi import Depends

from app.api.deps import DbSession
from app.modules.departments.service import DepartmentService


def get_department_service(session: DbSession) -> DepartmentService:
    return DepartmentService(session)


DepartmentServiceDep = Annotated[DepartmentService, Depends(get_department_service)]
