from typing import Annotated

from fastapi import Depends

from app.api.deps import CurrentUser, DbSession
from app.modules.departments.dependencies import DepartmentServiceDep
from app.modules.users.schemas import EmployeeListParams, EmployeeListQuery
from app.modules.users.service import UserService


def get_user_service(session: DbSession) -> UserService:
    return UserService(session)


UserServiceDep = Annotated[UserService, Depends(get_user_service)]


async def get_managed_employee_query(
    params: EmployeeListQuery, manager: CurrentUser, departments: DepartmentServiceDep
) -> EmployeeListParams:
    """Bộ lọc `department_id` phải là bộ phận manager quản lý, như `ManagedDepartment` trên path.

    Nhận cả bộ query chứ không riêng `department_id`: FastAPI gọi dependency trước khi validate
    query của endpoint, tách riêng thì `page` sai kèm bộ phận ngoài phạm vi trả 404 thay vì 422.
    """
    if params.department_id is not None:
        await departments.get_managed_department(manager.id, params.department_id)
    return params


ManagedEmployeeQuery = Annotated[EmployeeListParams, Depends(get_managed_employee_query)]
