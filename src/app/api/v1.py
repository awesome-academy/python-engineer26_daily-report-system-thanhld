"""Gom router của các module dưới tiền tố /api/v1 (Settings.api_v1_prefix).

Router được thêm dần theo kế hoạch trong docs/progress/10-day-plan.md:
/auth và /me (Ngày 1, 3), /admin (Ngày 4), /me/reports (Ngày 5), /manager (Ngày 6).
"""

from fastapi import APIRouter, Depends, status

from app.api.deps import require_roles
from app.core.config import get_settings
from app.core.exceptions import error_responses
from app.modules.auth.router import router as auth_router
from app.modules.departments.router import admin_department_router
from app.modules.reports.router import my_report_router
from app.modules.users.models import UserRole
from app.modules.users.router import admin_users_router, me_router

# Nhóm theo role: kiểm tra role một lần ở nhóm, endpoint bên trong không tự kiểm tra lại.
# Router của module phải include vào nhóm trước khi nhóm được include vào api_router,
# vì include_router chép route tại thời điểm gọi.
_ROLE_ERRORS = error_responses(status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)
admin_router = APIRouter(
    prefix="/admin", dependencies=[Depends(require_roles(UserRole.ADMIN))], responses=_ROLE_ERRORS
)
manager_router = APIRouter(
    prefix="/manager",
    dependencies=[Depends(require_roles(UserRole.MANAGER))],
    responses=_ROLE_ERRORS,
)
# Viết và xem báo cáo của mình chỉ dành cho role USER (Q3): nhóm không có tiền tố riêng, các
# router bên trong tự mang tiền tố /me/... cạnh các endpoint /me mọi role dùng được.
user_router = APIRouter(
    dependencies=[Depends(require_roles(UserRole.USER))], responses=_ROLE_ERRORS
)
admin_router.include_router(admin_department_router)
admin_router.include_router(admin_users_router)
user_router.include_router(my_report_router)

api_router = APIRouter(prefix=get_settings().api_v1_prefix)
api_router.include_router(auth_router)
api_router.include_router(me_router)
api_router.include_router(user_router)
api_router.include_router(admin_router)
api_router.include_router(manager_router)
