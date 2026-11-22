from datetime import date
from typing import Annotated

from fastapi import Depends, Query

from app.api.deps import CurrentUser, DbSession, Today
from app.core.validators import Id
from app.modules.departments.dependencies import DepartmentServiceDep
from app.modules.reports.exceptions import ReportExportDateOutOfRangeError
from app.modules.reports.schemas import ManagerReportListParams, ReportExportParams
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


async def get_report_export_params(
    manager: CurrentUser,
    departments: DepartmentServiceDep,
    today: Today,
    report_date: Annotated[
        date | None,
        Query(alias="date", description="Ngày báo cáo, mặc định hôm nay (giờ Việt Nam)"),
    ] = None,
    department_id: Annotated[
        Id | None, Query(description="Chỉ lấy bộ phận này (bộ phận tôi quản lý)")
    ] = None,
) -> ReportExportParams:
    """Query của export (M5): ngày không sau hôm nay, bộ phận lọc trong phạm vi như M3.

    Lỗi của tham số query (định dạng, ngày tương lai) có trước lỗi 404 phạm vi, như danh sách M3.
    Khai `date` ở đây chứ không bằng model như M3: field tên `date` trùng tên kiểu `date`.
    """
    report_date = report_date or today
    if report_date > today:
        raise ReportExportDateOutOfRangeError(today)
    if department_id is not None:
        await departments.get_managed_department(manager.id, department_id)
    return ReportExportParams(report_date=report_date, department_id=department_id)


ReportExportQuery = Annotated[ReportExportParams, Depends(get_report_export_params)]
