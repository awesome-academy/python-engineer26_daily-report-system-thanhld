from typing import Annotated

from fastapi import Depends

from app.api.deps import CurrentUser, DbSession, IdPath
from app.modules.departments.models import Department
from app.modules.departments.service import DepartmentService


def get_department_service(session: DbSession) -> DepartmentService:
    return DepartmentService(session)


DepartmentServiceDep = Annotated[DepartmentService, Depends(get_department_service)]


async def get_managed_department(
    department_id: IdPath, manager: CurrentUser, service: DepartmentServiceDep
) -> Department:
    return await service.get_managed_department(manager.id, department_id)


# Endpoint /manager có `{department_id}` trên URL nhận bộ phận qua alias này, không tự gọi policy:
# ngoài phạm vi hoặc không tồn tại thì 404 trước khi vào handler. Endpoint phải khai 404 trong
# `responses` của mình.
ManagedDepartment = Annotated[Department, Depends(get_managed_department)]
