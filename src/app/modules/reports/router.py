from fastapi import APIRouter, status

from app.api.deps import CurrentUser, Today
from app.core.constants import REPORT_BACKDATE_DAYS
from app.core.exceptions import error_responses
from app.modules.reports.dependencies import ReportServiceDep
from app.modules.reports.schemas import RecipientOut, ReportCreate, ReportOut

# Include vào nhóm role USER (api/v1.py): role được kiểm tra ở nhóm, 401, 403 khai ở nhóm.
my_report_router = APIRouter(prefix="/me", tags=["Cá nhân: báo cáo"])


@my_report_router.get(
    "/recipients",
    summary="Danh sách người nhận báo cáo",
    description=(
        "Manager đang hoạt động của bộ phận mình. Chưa thuộc bộ phận nào thì danh sách rỗng."
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
