from fastapi import APIRouter, status

from app.api.deps import CurrentUser, IdPath, Today
from app.core.constants import REPORT_BACKDATE_DAYS
from app.core.exceptions import error_responses
from app.core.pagination import Page
from app.modules.reports.dependencies import ReportServiceDep
from app.modules.reports.schemas import (
    RecipientOut,
    ReportCreate,
    ReportDetailOut,
    ReportListQuery,
    ReportOut,
    ReportSummaryOut,
)

# Include vào nhóm role USER (api/v1.py): role được kiểm tra ở nhóm, 401, 403 khai ở nhóm.
my_report_router = APIRouter(prefix="/me", tags=["Cá nhân: báo cáo"])


@my_report_router.get(
    "/recipients",
    summary="Danh sách người nhận báo cáo",
    description=(
        "Manager đăng nhập được của bộ phận mình. Chưa thuộc bộ phận nào thì danh sách rỗng."
    ),
)
async def list_my_recipients(user: CurrentUser, service: ReportServiceDep) -> list[RecipientOut]:
    return [RecipientOut.model_validate(item) for item in await service.list_recipients(user)]


@my_report_router.post(
    "/reports",
    status_code=status.HTTP_201_CREATED,
    summary="Tạo báo cáo hằng ngày",
    description=(
        f"Mỗi ngày một báo cáo, cho hôm nay hoặc tối đa {REPORT_BACKDATE_DAYS} ngày trước "
        "(giờ Việt Nam). Người nhận lấy từ `GET /me/recipients`; bỏ trống `recipient_ids` thì "
        "gửi cho mọi manager của bộ phận. Báo cáo đã tạo không sửa, xóa được."
    ),
    responses=error_responses(status.HTTP_409_CONFLICT, status.HTTP_422_UNPROCESSABLE_CONTENT),
)
async def create_my_report(
    data: ReportCreate, user: CurrentUser, service: ReportServiceDep, today: Today
) -> ReportOut:
    return ReportOut.model_validate(await service.create_report(user, data, today=today))


@my_report_router.get(
    "/reports",
    summary="Lịch sử báo cáo của tôi",
    description=(
        "Lọc theo ngày báo cáo từ `date_from` đến `date_to`, sắp ngày mới nhất trước. Mỗi báo "
        "cáo không kèm người nhận; xem ở `GET /me/reports/{report_id}`."
    ),
    responses=error_responses(status.HTTP_422_UNPROCESSABLE_CONTENT),
)
async def list_my_reports(
    params: ReportListQuery, user: CurrentUser, service: ReportServiceDep
) -> Page[ReportSummaryOut]:
    reports, total = await service.list_my_reports(user, params)
    return Page[ReportSummaryOut].build(
        [ReportSummaryOut.model_validate(report) for report in reports], total=total, params=params
    )


@my_report_router.get(
    "/reports/{report_id}",
    summary="Xem báo cáo của tôi",
    description=(
        "Gồm bộ phận lúc viết báo cáo và người nhận (sắp theo tên). Người nhận đã bị xóa vẫn "
        "hiện, `is_deleted` là `true` và không trả email. Báo cáo của người khác trả 404."
    ),
    responses=error_responses(status.HTTP_404_NOT_FOUND, status.HTTP_422_UNPROCESSABLE_CONTENT),
)
async def get_my_report(
    report_id: IdPath, user: CurrentUser, service: ReportServiceDep
) -> ReportDetailOut:
    return await service.get_my_report(user, report_id)
