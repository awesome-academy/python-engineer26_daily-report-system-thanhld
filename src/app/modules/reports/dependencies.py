from typing import Annotated

from fastapi import Depends, Query

from app.api.deps import CurrentUser, DbSession
from app.modules.departments.dependencies import DepartmentServiceDep
from app.modules.reports.schemas import ManagerReportListParams
from app.modules.reports.service import ReportService


def get_report_service(session: DbSession) -> ReportService:
    return ReportService(session)


ReportServiceDep = Annotated[ReportService, Depends(get_report_service)]


async def get_manager_report_params(
    params: Annotated[ManagerReportListParams, Query()],
    manager: CurrentUser,
    departments: DepartmentServiceDep,
) -> ManagerReportListParams:
    """Query của danh sách báo cáo; lọc theo bộ phận ngoài phạm vi trả 404 như `ManagedDepartment`.

    Nhận cả bộ query, không riêng `department_id`: FastAPI chạy dependency trước khi validate query
    của chính endpoint, nên tách riêng thì `?page=0&department_id=<ngoài phạm vi>` trả 404 thay vì
    422, sai thứ tự lỗi trong api-design.
    """
    if params.department_id is not None:
        await departments.get_managed_department(manager.id, params.department_id)
    return params


ManagerReportListQuery = Annotated[ManagerReportListParams, Depends(get_manager_report_params)]
